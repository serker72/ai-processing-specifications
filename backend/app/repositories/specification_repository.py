"""Репозиторий для работы с загрузками спецификаций клиентов."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import SpecificationRow, SpecificationUpload, UploadStatus


class SpecificationRepository:
    """CRUD-операции для сессий загрузки спецификаций."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        manager_id: UUID,
        file_key: str,
        status: UploadStatus = UploadStatus.pending,
    ) -> SpecificationUpload:
        """Создать запись о загрузке спецификации."""
        upload = SpecificationUpload(
            manager_id=manager_id,
            file_key=file_key,
            status=status,
        )
        self._session.add(upload)
        await self._session.flush()
        return upload

    async def get_by_id(self, upload_id: UUID) -> SpecificationUpload | None:
        """Получить сессию загрузки по ID."""
        return await self._session.get(SpecificationUpload, upload_id)

    async def update_status(self, upload_id: UUID, status: UploadStatus) -> None:
        """Обновить статус обработки."""
        upload = await self._session.get(SpecificationUpload, upload_id)
        if upload:
            upload.status = status
            await self._session.flush()

    async def update_mapping(self, upload_id: UUID, column_mapping: dict) -> None:
        """Сохранить маппинг колонок спецификации."""
        upload = await self._session.get(SpecificationUpload, upload_id)
        if upload:
            upload.column_mapping = column_mapping
            await self._session.flush()

    async def create_row(
        self,
        upload_id: UUID,
        row_number: int,
        raw_data: dict,
        matched_item_id: UUID | None = None,
        match_type: str | None = None,
        status: str | None = None,
    ) -> SpecificationRow:
        """Создать строку спецификации."""
        from app.models.models import MatchType, RowStatus

        row = SpecificationRow(
            upload_id=upload_id,
            row_number=row_number,
            raw_data=raw_data,
            matched_item_id=matched_item_id,
            match_type=MatchType(match_type) if match_type else None,
            status=status if status else RowStatus.pending,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def bulk_create_rows(
        self,
        upload_id: UUID,
        rows_data: list[dict],
    ) -> int:
        """Пакетно создать строки спецификации.

        Args:
            upload_id: ID сессии загрузки.
            rows_data: список dict с ключами row_number, raw_data.

        Returns:
            Количество созданных строк.
        """
        from app.models.models import SpecificationRow

        entities = [
            SpecificationRow(
                upload_id=upload_id,
                row_number=item["row_number"],
                raw_data=item["raw_data"],
            )
            for item in rows_data
        ]
        self._session.add_all(entities)
        await self._session.flush()
        return len(entities)
