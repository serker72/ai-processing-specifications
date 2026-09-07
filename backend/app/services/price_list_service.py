"""Сервис обработки прайс-листов: загрузка, превью, предсказание маппинга."""

import uuid
from typing import Any

from app.core.messages import CommonMessages
from app.repositories.price_list_repository import PriceListRepository
from app.schemas.confirm_mapping import ConfirmMappingRequest
from app.schemas.mapping import ColumnMappingPrediction
from app.services.excel_preview_service import ExcelPreviewService
from app.services.llm_service import LlmService
from app.services.minio_service import MinioService

# Максимальный размер загружаемого прайс-листа (50 МБ)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class FileTooLargeError(Exception):
    """Загруженный файл превышает допустимый размер."""


class PriceListService:
    """Оркестратор: загрузка прайс-листа в MinIO, превью, LLM-предсказание маппинга."""

    def __init__(
        self,
        minio: MinioService,
        excel_preview: ExcelPreviewService,
        llm: LlmService,
        price_list_repo: PriceListRepository,
    ) -> None:
        self._minio = minio
        self._excel_preview = excel_preview
        self._llm = llm
        self._price_list_repo = price_list_repo

    async def upload_and_predict(
        self,
        fileobj: Any,
        original_filename: str,
        admin_id: object,
    ) -> dict[str, object]:
        """Потоково загрузить прайс-лист в MinIO, прочитать превью, предсказать маппинг.

        fileobj — seekable file-like объект (SpooledTemporaryFile из UploadFile).
        Файл не читается в память целиком: в MinIO уходит потоково (multipart),
        превью читается лениво (openpyxl read_only).

        Возвращает:
        {
            "upload_id": "...",
            "file_key": "pricelists/<uuid>.xlsx",
            "file_url": "http://...",
            "preview": {...},
            "predicted_mapping": {...},
        }
        """
        # 0. Проверить размер (seek в конец и обратно)
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        if size > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(CommonMessages.FILE_TOO_LARGE)

        # 1. Потоково сохранить файл в MinIO (уникальный ключ, чтобы не перезаписать чужой прайс)
        file_key = f"pricelists/{uuid.uuid4().hex}-{original_filename}"
        await self._minio.create_bucket_if_not_exists()
        file_url = await self._minio.upload_fileobj(file_key, fileobj, content_type=XLSX_CONTENT_TYPE)

        # 2. Прочитать превью (первые 50 строк, ленивое чтение с диска)
        preview = self._excel_preview.read_preview(fileobj, max_rows=50)

        # 3. Предсказать маппинг через LLM: заголовки + образцы содержимого строк
        sample_rows = preview["rows"][: self.SAMPLE_ROWS_FOR_LLM]
        predicted_mapping = await self._predict_column_mapping(preview["headers"], sample_rows)

        # 4. Сохранить запись в БД
        upload = await self._price_list_repo.create(
            admin_id=admin_id,
            file_key=file_key,
        )
        await self._price_list_repo.update_mapping(upload.id, predicted_mapping.model_dump())

        return {
            "upload_id": str(upload.id),
            "file_key": file_key,
            "file_url": file_url,
            "preview": preview,
            "predicted_mapping": predicted_mapping.model_dump(),
        }

    async def confirm_mapping(
        self,
        upload_id: str,
        payload: ConfirmMappingRequest,
        admin_id: object,
    ) -> dict:
        """Подтвердить или отредактировать маппинг колонок.

        Записывает подтверждённый маппинг в БД, меняет статус на `processing`.
        """
        import uuid as _uuid

        upload = await self._price_list_repo.get_by_id(_uuid.UUID(upload_id))
        if not upload:
            raise FileNotFoundError(f"Загрузка {upload_id} не найдена")

        column_mapping = {
            "sku_column": payload.sku_column,
            "name_column": payload.name_column,
            "price_column": payload.price_column,
            "additional_columns": payload.additional_columns,
        }
        await self._price_list_repo.update_mapping(upload.id, column_mapping)
        await self._price_list_repo.update_status(upload.id, "processing")

        return {
            "upload_id": str(upload.id),
            "status": "processing",
            "mapping": column_mapping,
        }

    async def _parse_pricelist(self, file_key: str, column_mapping: dict) -> list[dict]:
        """Прочитать прайс-лист из MinIO и вернуть список строк по маппингу.

        Возвращает список dict с ключами: sku, name, price (если есть), description.
        """
        import io

        fileobj = io.BytesIO()
        client = await self._minio._get_client()
        await client.download_fileobj(
            Bucket=self._minio._bucket,
            Key=file_key,
            Fileobj=fileobj,
        )
        fileobj.seek(0)

        preview = self._excel_preview.read_preview(fileobj, max_rows=None)  # все строки
        rows: list[dict] = []
        sku_idx = preview["headers"].index(column_mapping["sku_column"])
        name_idx = preview["headers"].index(column_mapping["name_column"])
        price_idx = None
        if column_mapping.get("price_column"):
            try:
                price_idx = preview["headers"].index(column_mapping["price_column"])
            except ValueError:
                pass

        for row in preview["rows"]:
            sku = str(row[sku_idx]) if sku_idx < len(row) else ""
            name = str(row[name_idx]) if name_idx < len(row) else ""
            price = row[price_idx] if price_idx is not None and price_idx < len(row) else None
            description = f"{sku} {name}" if sku else name
            rows.append({"sku": sku, "name": name, "price": price, "description": description})

        return rows

    # Сколько строк данных передавать LLM как образцы содержимого колонок
    SAMPLE_ROWS_FOR_LLM = 5

    async def _predict_column_mapping(
        self, headers: list[str], sample_rows: list[list[object]] | None = None
    ) -> ColumnMappingPrediction:
        """Запросить у LLM предсказание ролей колонок.

        Используются и заголовки, и образцы содержимого (первые
        SAMPLE_ROWS_FOR_LLM строк данных) — по одному заголовку невозможно
        надёжно определить роль, если он неинформативный или неоднозначный.
        """
        headers_str = ", ".join(f'"{h}"' for h in headers)
        prompt_parts = [
            "Определи роли колонок прайс-листа по их названиям и содержимому.",
            f"Колонки таблицы: [{headers_str}].",
        ]
        if sample_rows:
            rows_str = "\n".join(
                " | ".join(str(v) if v is not None else "" for v in row) for row in sample_rows
            )
            prompt_parts.append(f"Образцы содержимого (первые строки данных):\n{rows_str}")
        prompt_parts.extend(
            [
                "",
                "Верни JSON строго по схеме:",
                (
                    '{"sku_column": "<колонка с артикулом/кодом товара>", '
                    '"name_column": "<колонка с наименованием товара>", '
                    '"price_column": "<колонка с ценой или null>", '
                    '"additional_columns": {"<имя колонки>": "<роль>"}\n'
                    "}"
                ),
                "",
                (
                    "Значения — точные названия колонок из списка выше. Пример: "
                    '{"sku_column": "Код", "name_column": "Товар", "price_column": "Цена", '
                    '"additional_columns": {}}'
                ),
            ]
        )
        prompt = "\n".join(prompt_parts)
        # Компактная схема без description — иначе модель копирует описание вместо ответа
        schema = {
            "type": "object",
            "properties": {
                "sku_column": {"type": "string"},
                "name_column": {"type": "string"},
                "price_column": {"type": ["string", "null"]},
                "additional_columns": {"type": "object"},
            },
            "required": ["sku_column", "name_column", "price_column", "additional_columns"],
        }
        result = await self._llm.complete_json(
            "Ты определяешь роли колонок прайс-листа. Отвечай только JSON без пояснений.",
            prompt,
            schema,
        )
        return ColumnMappingPrediction.from_llm_response(result)
