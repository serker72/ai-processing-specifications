"""Репозиторий для работы с загрузками прайс-листов."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import PriceListUpload, UploadStatus


class PriceListRepository:
    """CRUD-операции для сессий загрузки прайс-листов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        admin_id: UUID,
        file_key: str,
        status: UploadStatus = UploadStatus.pending,
    ) -> PriceListUpload:
        """Создать запись о загрузке прайс-листа."""
        upload = PriceListUpload(
            admin_id=admin_id,
            file_key=file_key,
            status=status,
        )
        self._session.add(upload)
        await self._session.flush()
        return upload

    async def get_by_id(self, upload_id: UUID) -> PriceListUpload | None:
        """Получить сессию загрузки по ID."""
        return await self._session.get(PriceListUpload, upload_id)

    async def update_status(self, upload_id: UUID, status: UploadStatus) -> None:
        """Обновить статус обработки."""
        upload = await self._session.get(PriceListUpload, upload_id)
        if upload:
            upload.status = status
            await self._session.flush()

    async def update_mapping(self, upload_id: UUID, column_mapping: dict) -> None:
        """Сохранить предсказанный маппинг колонок (статус остаётся pending до подтверждения админом)."""
        upload = await self._session.get(PriceListUpload, upload_id)
        if upload:
            upload.column_mapping = column_mapping
            await self._session.flush()
