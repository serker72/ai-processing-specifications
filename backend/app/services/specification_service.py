"""Сервис обработки спецификаций: загрузка, превью, предсказание маппинга колонок.

Файл передаётся как поток (SpooledTemporaryFile), не читается в память целиком.

Задача 5.1: LLM-маппинг вынесен из HTTP-запроса в Celery-таску — быстрая часть
(`create_upload`) сохраняет файл и создаёт запись, медленная (`predict_mapping`)
выполняется в фоне по образцу `PriceListService`.
"""

import uuid
from typing import Any

from app.core.messages import ClientMessages, CommonMessages, SpecificationMessages
from app.models.models import RowStatus, UploadStatus
from app.repositories.client_repository import ClientRepository
from app.repositories.price_list_repository import PriceListRepository
from app.repositories.specification_repository import SpecificationRepository
from app.schemas.specification import (
    MatchedCatalogItem,
    RowMatchCandidate,
    RowMatchesResponse,
    SpecificationMappingPrediction,
    SpecificationRowItem,
    SpecificationUploadDetail,
    SpecificationUploadItem,
)
from app.services.excel_preview_service import ExcelPreviewService
from app.services.file_naming import StoredFileKey
from app.services.llm_service import LlmService
from app.services.minio_service import MinioService

# Максимальный размер загружаемой спецификации (50 МБ)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


class FileTooLargeError(Exception):
    """Загруженный файл превышает допустимый размер."""


class SpecificationService:
    """Оркестратор: загрузка спецификации в MinIO, превью, LLM-предсказание маппинга."""

    XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(
        self,
        minio: MinioService,
        excel_preview: ExcelPreviewService,
        llm: LlmService,
        specification_repo: SpecificationRepository,
        client_repo: ClientRepository,
        price_list_repo: PriceListRepository,
    ) -> None:
        self._minio = minio
        self._excel_preview = excel_preview
        self._llm = llm
        self._spec_repo = specification_repo
        self._client_repo = client_repo
        self._price_list_repo = price_list_repo

    async def is_catalog_updating(self) -> bool:
        """Идёт ли сейчас векторизация каталога (загрузка прайса в статусе processing).

        Защита от гонки (Задача 5.1): параллельные `catalog.vectorize` и
        `specification.process` дают недетерминированный матчинг — матчинг видит
        «частично обновлённый» каталог. Загрузка спецификации отклоняется (409),
        пока прайс-лист в обработке.
        """
        counts = await self._price_list_repo.count_by_status()
        return counts.get(UploadStatus.processing.value, 0) > 0

    async def create_upload(
        self,
        fileobj: Any,
        original_filename: str,
        manager_id: object,
        client_id: uuid.UUID,
    ) -> dict:
        """Быстрая часть (задача 5.1): загрузить файл в MinIO, создать запись `pending`.

        LLM-предсказание маппинга здесь не выполняется — его делает Celery-таска
        `specification.predict_mapping`. Возвращает upload_id для SSE-подписки.
        """
        # 0. Проверить размер
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        if size > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(CommonMessages.FILE_TOO_LARGE)

        # 0.1 Проверить, что клиент существует
        if await self._client_repo.get_by_id(client_id) is None:
            raise ValueError(ClientMessages.NOT_FOUND)

        # 1. Сохранить файл в MinIO
        file_key = f"specifications/{uuid.uuid4().hex}-{original_filename}"
        await self._minio.create_bucket_if_not_exists()
        file_url = await self._minio.upload_fileobj(
            file_key, fileobj, content_type=self.XLSX_CONTENT_TYPE
        )

        # 2. Создать запись в БД со статусом «ожидает предсказания маппинга»
        upload = await self._spec_repo.create(
            manager_id=manager_id,
            client_id=client_id,
            file_key=file_key,
        )

        return {
            "upload_id": str(upload.id),
            "file_key": file_key,
            "file_url": file_url,
            "status": upload.status.value,
        }

    async def predict_mapping(self, upload_id: str) -> dict:
        """Медленная часть (задача 5.1): превью + LLM-предсказание маппинга колонок.

        Вызывается из Celery-таски. Переходы статусов:
        pending → mapping_processing → mapping_predicted | failed.
        После успешного предсказания здесь же ставится таска матчинга строк.
        """
        upload = await self._spec_repo.get_by_id(uuid.UUID(upload_id))
        if upload is None:
            raise FileNotFoundError(SpecificationMessages.UPLOAD_NOT_FOUND)

        await self._spec_repo.update_status(upload.id, UploadStatus.mapping_processing)
        await self._spec_repo.commit()

        try:
            # 1. Скачать файл и прочитать превью (первые 50 строк, лениво)
            fileobj = await self._minio.download_fileobj(upload.file_key)
            preview = self._excel_preview.read_preview(fileobj, max_rows=50)

            # 2. Предсказать маппинг через LLM (заголовки + образцы данных)
            predicted_mapping = await self._predict_column_mapping(
                preview["headers"], preview["rows"]
            )

            # 3. Сохранить предсказанный маппинг и обновить статус
            await self._spec_repo.update_mapping(upload.id, predicted_mapping.model_dump())
            await self._spec_repo.update_status(upload.id, UploadStatus.mapping_predicted)
            await self._spec_repo.commit()

            # 4. Ждать подтверждения маппинга менеджером (endpoint confirm_mapping).
            # Матчинг строк запускается после подтверждения, не автоматически.

            return {
                "upload_id": str(upload.id),
                "status": UploadStatus.mapping_predicted.value,
                "mapping": predicted_mapping.model_dump(),
            }
        except Exception:
            await self._spec_repo.update_status(upload.id, UploadStatus.failed)
            await self._spec_repo.commit()
            raise

    async def get_mapping_preview(self, upload_id: uuid.UUID, manager_id: uuid.UUID) -> dict:
        """Предпросмотр маппинга колонок: заголовки файла + предсказание LLM.

        Используется UI для экрана подтверждения после события `mapping_predicted`:
        полный список колонок берётся из файла, предсказанные роли — из column_mapping.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(SpecificationMessages.UPLOAD_NOT_FOUND)

        fileobj = await self._minio.download_fileobj(upload.file_key)
        preview = self._excel_preview.read_preview(fileobj, max_rows=5)
        return {
            "upload_id": str(upload.id),
            "status": upload.status.value,
            "headers": preview["headers"],
            "mapping": upload.column_mapping or {},
        }

    async def confirm_mapping(self, upload_id: uuid.UUID, mapping: dict) -> dict:
        """Подтвердить/отредактировать маппинг колонок спецификации.

        После подтверждения запускается фоновая обработка строк (матчинг).
        Если маппинг уже подтверждён или обработка идёт — ValueError.
        """
        upload = await self._spec_repo.get_by_id(upload_id)
        if upload is None:
            raise LookupError(SpecificationMessages.UPLOAD_NOT_FOUND)

        # Маппинг должен быть в статусе mapping_predicted (не подтверждён ранее)
        if upload.status != UploadStatus.mapping_predicted:
            raise ValueError(
                f"Подтверждение доступно только для статуса mapping_predicted, "
                f"текущий статус: {upload.status.value}"
            )

        await self._spec_repo.update_mapping(upload_id, mapping)
        await self._spec_repo.update_status(upload_id, UploadStatus.processing)
        await self._spec_repo.commit()

        # Запустить фоновую обработку строк через Matching Engine
        from app.worker.tasks import process_specification

        process_specification.delay(str(upload_id), str(upload.manager_id))

        return {
            "upload_id": str(upload_id),
            "status": UploadStatus.processing.value,
            "mapping": mapping,
        }

    async def list_uploads(self, manager_id: uuid.UUID) -> list[SpecificationUploadItem]:
        """Список ранее загруженных спецификаций менеджера (свежие — первыми)."""
        uploads = await self._spec_repo.list_by_manager(manager_id)
        return [
            SpecificationUploadItem(
                id=str(upload.id),
                filename=StoredFileKey.original_name(upload.file_key),
                status=upload.status.value,
                created_at=upload.created_at,
                client_id=str(upload.client_id),
                client_name=upload.client.name if upload.client else None,
            )
            for upload in uploads
        ]

    async def get_upload(self, upload_id: uuid.UUID, manager_id: uuid.UUID) -> SpecificationUploadDetail:
        """Карточка спецификации: файл, статус, маппинг, сводка по строкам.

        Raises:
            LookupError: загрузка не найдена либо принадлежит другому менеджеру.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(CommonMessages.NOT_FOUND)

        return SpecificationUploadDetail(
            id=str(upload.id),
            filename=StoredFileKey.original_name(upload.file_key),
            status=upload.status.value,
            created_at=upload.created_at,
            client_id=str(upload.client_id),
            client_name=upload.client.name if upload.client else None,
            column_mapping=upload.column_mapping,
            rows_total=await self._spec_repo.count_rows(upload.id),
            rows_by_status=await self._spec_repo.count_rows_by_status(upload.id),
        )

    async def list_rows(
        self,
        upload_id: uuid.UUID,
        manager_id: uuid.UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SpecificationRowItem], int]:
        """Страница строк спецификации с результатом матчинга.

        Returns:
            (строки страницы, общее число строк с учётом фильтра).

        Raises:
            LookupError: загрузка не найдена либо принадлежит другому менеджеру.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(CommonMessages.NOT_FOUND)

        rows = await self._spec_repo.list_rows(
            upload_id=upload.id,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        total = await self._spec_repo.count_rows(upload.id, status)

        items = [self._row_item(row, raw_name=str((row.raw_data or {}).get("raw_name") or "")) for row in rows]
        return items, total

    async def commit_upload(self) -> None:
        """Зафиксировать загрузку до постановки таски: воркер должен увидеть запись."""
        await self._spec_repo.commit()

    async def retry(self, upload_id: uuid.UUID, manager_id: uuid.UUID) -> dict[str, object]:
        """Перезапустить обработку упавшей спецификации.

        Повторный матчинг использует уже подтверждённый `column_mapping`; старые
        (частичные) строки удаляются, чтобы повторное чтение файла не дало дублей.
        Допускается только для статуса `failed`.

        Raises:
            LookupError: загрузки нет либо она принадлежит другому менеджеру.
            ValueError: статус не `failed` либо маппинг не подтверждён.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(CommonMessages.NOT_FOUND)
        if upload.status != UploadStatus.failed:
            raise ValueError(SpecificationMessages.RETRY_NOT_FAILED)
        if not upload.column_mapping:
            raise ValueError(SpecificationMessages.NO_MAPPING)

        await self._spec_repo.delete_rows(upload.id)
        await self._spec_repo.update_status(upload.id, UploadStatus.processing)
        return {"upload_id": str(upload.id), "status": UploadStatus.processing.value}

    async def update_row_status(
        self,
        upload_id: uuid.UUID,
        manager_id: uuid.UUID,
        row_id: uuid.UUID,
        status: str,
        catalog_item_id: uuid.UUID | None,
        matching_service: Any,
    ) -> SpecificationRowItem:
        """Изменить статус строки: подтвердить с позицией (Tier-1), исключить или вернуть в обработку.

        При подтверждении строка сопоставляется с выбранной позицией каталога,
        а наименование добавляется в HistoricalMatch — следующий такой же
        raw_name сматчится мгновенно на Tier-1.

        Из `excluded` разрешены переходы:
        * `excluded → unmatched` — возврат в обработку (кнопка «Возвратить»);
        * `excluded → matched` — если строка уже имеет позицию каталога.

        Raises:
            LookupError: загрузка или строка не найдены либо принадлежат другому менеджеру.
            ValueError: неподходящий статус или некорректная пара статус/позиция.
        """
        allowed = {RowStatus.confirmed.value, RowStatus.excluded.value, RowStatus.unmatched.value, RowStatus.matched.value}
        if status not in allowed:
            raise ValueError(SpecificationMessages.ROW_STATUS_UNSUPPORTED)

        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(CommonMessages.NOT_FOUND)

        row = await self._spec_repo.get_row(upload.id, row_id)
        if row is None:
            raise LookupError(SpecificationMessages.ROW_NOT_FOUND)

        # Исключение
        if status == RowStatus.excluded.value:
            await self._spec_repo.update_row_status(row_id, RowStatus.excluded)
            await self._spec_repo.commit()
            return self._row_item(row, raw_name=self._row_raw_name(row))

        # Возврат в обработку: unmatched — без позиции; matched — если есть matched_item
        if status in (RowStatus.unmatched.value, RowStatus.matched.value):
            if status == RowStatus.matched.value and row.matched_item_id is None:
                raise ValueError(SpecificationMessages.REINSTATE_REQUIRES_ITEM)
            await self._spec_repo.update_row_status(row_id, RowStatus(status))
            await self._spec_repo.commit()
            updated = await self._spec_repo.get_row(upload.id, row_id)
            if updated is None:
                return self._row_item(row, raw_name=self._row_raw_name(row))
            return self._row_item(updated, raw_name=self._row_raw_name(row))

        # Подтверждение: позиция обязательна (можно передать явно, иначе — уже
        # сопоставленная строке) и должна существовать в каталоге
        item_id = catalog_item_id or (
            row.matched_item_id if row.matched_item_id is not None else None
        )
        if item_id is None:
            raise ValueError(SpecificationMessages.CONFIRM_REQUIRES_ITEM)

        catalog_item = await self._spec_repo.get_catalog_item(item_id)
        if catalog_item is None:
            raise LookupError(SpecificationMessages.CATALOG_ITEM_NOT_FOUND)

        raw_name = self._row_raw_name(row)
        await self._spec_repo.confirm_row(
            row_id,
            item_id,
            snapshot_name=catalog_item.name,
            snapshot_sku=catalog_item.sku,
            snapshot_price=float(catalog_item.price) if catalog_item.price is not None else None,
            snapshot_unit=catalog_item.unit,
        )
        await matching_service.confirm_match(
            raw_name=raw_name,
            catalog_item_id=str(item_id),
            tier="manual",
        )
        await self._spec_repo.commit()

        updated = await self._spec_repo.get_row(upload.id, row_id)
        if updated is None:  # строка удалена конкурентно — отдаём снимок до обновления
            return self._row_item(row, raw_name=raw_name)
        return self._row_item(updated, raw_name=raw_name)

    async def get_row_matches(
        self,
        upload_id: uuid.UUID,
        manager_id: uuid.UUID,
        row_id: uuid.UUID,
        limit: int,
        matching_service: Any,
    ) -> RowMatchesResponse:
        """Топ-N кандидатов векторного поиска для строки (для выбора позиции в UI).

        **Ленивый матчинг:** сначала читаем сохранённых кандидатов из таблицы.
        Если их нет — делаем векторный поиск, сохраняем и возвращаем.
        Это предотвращает повторный векторный поиск при каждом открытии модалки
        после подтверждения Tier-1 (когда candidates были бы пустыми).

        Raises:
            LookupError: загрузка или строка не найдены либо принадлежат другому менеджеру.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise LookupError(CommonMessages.NOT_FOUND)

        row = await self._spec_repo.get_row(upload.id, row_id)
        if row is None:
            raise LookupError(SpecificationMessages.ROW_NOT_FOUND)

        raw_name = self._row_raw_name(row)

        # 1. Сначала читаем сохранённых кандидатов
        saved_candidates = await self._spec_repo.get_row_candidates(row_id)

        if saved_candidates:
            # Кандидаты есть — используем их
            candidates_list = [
                {
                    "id": str(c.catalog_item.id),
                    "sku": c.catalog_item.sku,
                    "name": c.catalog_item.name,
                    "unit": c.catalog_item.unit,
                    "price": c.catalog_item.price,
                    "similarity": c.score,
                }
                for c in saved_candidates
            ]
        else:
            # 2. Ленивый матчинг: векторный поиск + сохранение
            result = await matching_service.match_row(raw_name=raw_name, limit=limit)
            candidates_list = result["candidates"]
            if candidates_list and result["tier"] == "top_n":
                await self._spec_repo.save_row_candidates(
                    row_id=row_id,
                    candidates=candidates_list,
                    match_tier=result["tier"],
                )

        matched_item: MatchedCatalogItem | None = None
        if row.matched_item is not None:
            item = row.matched_item
            matched_item = MatchedCatalogItem(
                id=str(item.id), sku=item.sku, name=item.name, unit=item.unit, price=item.price
            )

        return RowMatchesResponse(
            row_id=str(row.id),
            raw_name=raw_name,
            match_type=row.match_type.value if row.match_type else None,
            matched_item=matched_item,
            candidates=[
                RowMatchCandidate(
                    id=str(c["id"]),
                    sku=c["sku"],
                    name=c["name"],
                    unit=c["unit"],
                    price=c["price"],
                    similarity=float(c["similarity"]),
                )
                for c in candidates_list
            ],
        )

    @staticmethod
    def _row_raw_name(row: Any) -> str:
        """Наименование из исходных данных строки (raw_data.raw_name)."""
        return str((row.raw_data or {}).get("raw_name") or "")

    @staticmethod
    def _row_item(row: Any, raw_name: str) -> SpecificationRowItem:
        """ORM-строку → элемент ответа (для действий над отдельной строкой)."""
        raw = row.raw_data or {}
        item = row.matched_item
        return SpecificationRowItem(
            id=str(row.id),
            row_number=row.row_number,
            raw_name=raw_name,
            quantity=SpecificationService._as_number(raw.get("quantity")),
            unit=raw.get("unit"),
            price=SpecificationService._as_number(raw.get("price")),
            match_type=row.match_type.value if row.match_type else None,
            status=row.status.value if row.status else None,
            matched_item=(
                MatchedCatalogItem(
                    id=str(item.id), sku=item.sku, name=item.name, unit=item.unit, price=item.price
                )
                if item is not None
                else None
            ),
            is_overridden=row.is_overridden,
            snapshot_item_name=row.snapshot_item_name,
            snapshot_sku=row.snapshot_sku,
            snapshot_price=float(row.snapshot_price) if row.snapshot_price is not None else None,
            snapshot_unit=row.snapshot_unit,
        )

    @staticmethod
    def _as_number(raw: object) -> float | None:
        """Значение числовой колонки из raw_data → float (текст без числа → None)."""
        if raw is None or isinstance(raw, bool):
            return None
        if isinstance(raw, int | float):
            return float(raw)
        text = str(raw).replace("\u00a0", " ").replace(" ", "").replace(",", ".").strip()
        try:
            return float(text)
        except ValueError:
            return None

    async def _predict_column_mapping(
        self, headers: list[str], sample_rows: list[list[object]] | None = None
    ) -> SpecificationMappingPrediction:
        """Запросить у LLM предсказание ролей колонок спецификации.

        Используются и заголовки, и образцы содержимого (первые SAMPLE_ROWS_FOR_LLM
        строк данных) — по одному заголовку невозможно надёжно определить роль,
        если он неинформативный или неоднозначный.
        """
        headers_str = ", ".join(f'"{h}"' for h in headers)
        prompt_parts = [
            "Определи роли колонок спецификации клиента по их названиям и содержимому.",
            f"Колонки таблицы: [{headers_str}].",
        ]
        if sample_rows:
            rows_str = "\n".join(
                " | ".join(str(v) if v is not None else "" for v in row) for row in sample_rows[:5]
            )
            prompt_parts.append(f"Образцы содержимого (первые строки данных):\n{rows_str}")
        prompt_parts.extend(
            [
                "",
                "Верни JSON строго по схеме:",
                (
                    '{"name_column": "<колонка с наименованием товара>", '
                    '"quantity_column": "<колонка с количеством или null>", '
                    '"unit_column": "<колонка с единицей измерения или null>", '
                    '"price_column": "<колонка с ценой или null>", '
                    '"additional_columns": {"<имя колонки>": "<роль>"}\n'
                    "}"
                ),
                "",
                (
                    "Значения — точные названия колонок из списка выше (строки, не объекты). "
                    "Пример: "
                    '{"name_column": "Наименование", "quantity_column": "Количество", '
                    '"unit_column": "Ед.", "price_column": "Цена", '
                    '"additional_columns": {}}'
                ),
            ]
        )
        prompt = "\n".join(prompt_parts)
        schema = {
            "type": "object",
            "properties": {
                "name_column": {"type": "string"},
                "quantity_column": {"type": ["string", "null"]},
                "unit_column": {"type": ["string", "null"]},
                "price_column": {"type": ["string", "null"]},
                "additional_columns": {"type": "object"},
            },
            "required": [
                "name_column",
                "quantity_column",
                "unit_column",
                "price_column",
                "additional_columns",
            ],
        }
        result = await self._llm.complete_json(
            "Ты определяешь роли колонок спецификации. Отвечай только JSON без пояснений.",
            prompt,
            schema,
        )
        # Валидировать имена колонок из реального файла — LLM не должен выдумывать
        return SpecificationMappingPrediction.from_llm_response(result, valid_columns=set(headers))
