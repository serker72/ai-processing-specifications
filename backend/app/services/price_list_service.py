"""Сервис обработки прайс-листов: загрузка, превью, предсказание маппинга."""

import uuid
from typing import Any

from app.core.messages import CommonMessages, PriceListMessages
from app.models.models import UploadStatus
from app.repositories.price_list_repository import PriceListRepository
from app.schemas.confirm_mapping import ConfirmMappingRequest
from app.schemas.mapping import ColumnMappingPrediction
from app.schemas.price_list import PriceListUploadItem
from app.services.excel_preview_service import ExcelPreviewService
from app.services.file_naming import StoredFileKey
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

    async def list_uploads(
        self, status: UploadStatus | None = None
    ) -> tuple[list[PriceListUploadItem], dict[str, int]]:
        """История загрузок прайс-листов (свежие — первыми) + счётчики по статусам.

        Счётчики считаются по всем загрузкам, а не по отфильтрованным: иначе
        выбранный статус обнулил бы счётчики остальных. Статусы без загрузок
        возвращаются нулём, чтобы UI не дорисовывал пустые чипы сам.
        """
        uploads = await self._price_list_repo.list_filtered(status)
        items = [
            PriceListUploadItem(
                id=str(upload.id),
                filename=StoredFileKey.original_name(upload.file_key),
                admin_email=upload.admin.email if upload.admin else "",
                status=upload.status.value,
                created_at=upload.created_at,
            )
            for upload in uploads
        ]

        counts = {upload_status.value: 0 for upload_status in UploadStatus}
        counts.update(await self._price_list_repo.count_by_status())
        return items, counts

    async def get_preview(self, upload_id: str) -> dict[str, object]:
        """Превью прайс-листа из MinIO (50 строк) + сохранённый маппинг из БД.

        Для UI подтверждения маппинга: админ видит заголовки и строки файла
        вместе с предсказанным/сохранённым маппингом. FileNotFoundError —
        загрузки с таким ID нет.
        """
        upload = await self._price_list_repo.get_by_id(uuid.UUID(upload_id))
        if not upload:
            raise FileNotFoundError(PriceListMessages.UPLOAD_NOT_FOUND)

        fileobj = await self._minio.download_fileobj(upload.file_key)
        preview = self._excel_preview.read_preview(fileobj, max_rows=self._excel_preview.MAX_PREVIEW_ROWS)

        return {
            "upload_id": str(upload.id),
            "filename": StoredFileKey.original_name(upload.file_key),
            "status": upload.status.value,
            "sheets": preview["sheets"],
            "headers": preview["headers"],
            "rows": preview["rows"],
            "total_rows": preview["total_rows"],
            "column_mapping": upload.column_mapping,
        }

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

        # 4. Сохранить запись в БД: маппинг + статус «ожидает подтверждения админом»
        upload = await self._price_list_repo.create(
            admin_id=admin_id,
            file_key=file_key,
        )
        await self._price_list_repo.update_mapping(upload.id, predicted_mapping.model_dump())
        await self._price_list_repo.update_status(upload.id, UploadStatus.mapping_predicted)

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

        Записывает подтверждённый маппинг в БД и переводит загрузку в `processing`:
        дальше админ-эндпоинт ставит в очередь Celery-таску векторизации каталога.
        """
        import uuid as _uuid

        upload = await self._price_list_repo.get_by_id(_uuid.UUID(upload_id))
        if not upload:
            raise FileNotFoundError(f"Загрузка {upload_id} не найдена")

        column_mapping = {
            "sku_column": payload.sku_column,
            "name_column": payload.name_column,
            "price_column": payload.price_column,
            "unit_column": payload.unit_column,
            "additional_columns": payload.additional_columns,
        }
        await self._price_list_repo.update_mapping(upload.id, column_mapping)
        await self._price_list_repo.update_status(upload.id, UploadStatus.processing)

        return {
            "upload_id": str(upload.id),
            "status": UploadStatus.processing.value,
            "mapping": column_mapping,
        }

    async def commit_upload(self) -> None:
        """Зафиксировать загрузку до постановки таски: воркер должен увидеть запись."""
        await self._price_list_repo.commit()

    async def parse_pricelist(self, file_key: str, column_mapping: dict) -> list[dict]:
        """Прочитать прайс-лист из MinIO и вернуть список строк по маппингу.

        Возвращает список dict с ключами: sku, name, unit, price, description.
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
        headers = preview["headers"]

        def index_of(column_name: str | None) -> int | None:
            """Номер колонки в листе по её имени из маппинга (None, если колонки нет)."""
            if not column_name:
                return None
            try:
                return headers.index(column_name)
            except ValueError:
                return None

        sku_idx = index_of(column_mapping.get("sku_column"))
        name_idx = index_of(column_mapping.get("name_column"))
        price_idx = index_of(column_mapping.get("price_column"))
        unit_idx = index_of(column_mapping.get("unit_column"))

        def value(row: list, idx: int | None) -> object | None:
            """Значение ячейки строки по номеру колонки (None, если колонки нет)."""
            return row[idx] if idx is not None and idx < len(row) else None

        rows: list[dict] = []
        for row in preview["rows"]:
            sku = str(value(row, sku_idx) or "").strip()
            name = str(value(row, name_idx) or "").strip()
            if not name:
                continue  # Строки без наименования в каталог не попадают
            description = f"{sku} {name}" if sku else name
            rows.append(
                {
                    "sku": sku,
                    "name": name,
                    "unit": (str(value(row, unit_idx)).strip() if value(row, unit_idx) is not None else None),
                    "price": self._to_float(value(row, price_idx)),
                    "description": description,
                }
            )

        return rows

    @staticmethod
    def _to_float(raw: object | None) -> float | None:
        """Цена из ячейки Excel → float (пустое, текст без чисел → None)."""
        if raw is None or isinstance(raw, bool):
            return None
        if isinstance(raw, int | float):
            return float(raw)
        text = str(raw).replace("\u00a0", " ").replace(" ", "").replace(",", ".").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

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
