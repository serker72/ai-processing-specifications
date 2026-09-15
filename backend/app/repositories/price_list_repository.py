"""Репозиторий для работы с загрузками прайс-листов."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def commit(self) -> None:
        """Зафиксировать запись о загрузке до постановки Celery-таски в очередь.

        Иначе воркер может выбрать задачу раньше, чем unit-of-work запроса
        завершится коммитом, и не найти upload в базе.
        """
        await self._session.commit()

    async def list_filtered(self, status: UploadStatus | None = None) -> list[PriceListUpload]:
        """Все загрузки, свежие первыми; с status — только этого статуса."""
        stmt = (
            select(PriceListUpload)
            .options(selectinload(PriceListUpload.admin))
            .order_by(PriceListUpload.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(PriceListUpload.status == status)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        """Сколько загрузок в каждом статусе (по всем загрузкам, без фильтра).

        Пустые статусы здесь отсутствуют — нули подставляет сервис.
        """
        stmt = select(PriceListUpload.status, func.count()).group_by(PriceListUpload.status)

        result = await self._session.execute(stmt)
        return {status.value: total for status, total in result.all()}

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
