"""Репозиторий для работы с загрузками спецификаций клиентов."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def commit(self) -> None:
        """Зафиксировать запись о загрузке до постановки Celery-таски в очередь.

        Иначе воркер может выбрать задачу раньше, чем unit-of-work запроса
        завершится коммитом, и не найти upload в базе.
        """
        await self._session.commit()

    async def list_by_manager(self, manager_id: UUID) -> list[SpecificationUpload]:
        """Список загрузок спецификаций менеджера, свежие — первыми."""
        result = await self._session.execute(
            select(SpecificationUpload)
            .where(SpecificationUpload.manager_id == manager_id)
            .order_by(SpecificationUpload.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_status(self, upload_id: UUID, status: UploadStatus) -> None:
        """Обновить статус обработки."""
        upload = await self._session.get(SpecificationUpload, upload_id)
        if upload:
            upload.status = status
            await self._session.flush()

    async def get_for_manager(self, upload_id: UUID, manager_id: UUID) -> SpecificationUpload | None:
        """Загрузка спецификации, только если она принадлежит менеджеру.

        Чужая загрузка возвращается как None — проверка владельца выполняется
        здесь, чтобы эндпоинт не отличал «нет файла» от «файл другого менеджера».
        """
        result = await self._session.execute(
            select(SpecificationUpload).where(
                SpecificationUpload.id == upload_id,
                SpecificationUpload.manager_id == manager_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_rows(
        self,
        upload_id: UUID,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[SpecificationRow]:
        """Страница строк спецификации с сопоставленной позицией каталога.

        Args:
            upload_id: сессия загрузки.
            status: фильтр по статусу строки (RowStatus.value), None — все.
            offset: смещение страницы.
            limit: размер страницы.
        """
        statement = (
            select(SpecificationRow)
            .options(selectinload(SpecificationRow.matched_item))
            .where(SpecificationRow.upload_id == upload_id)
        )
        if status:
            statement = statement.where(SpecificationRow.status == status)
        statement = statement.order_by(SpecificationRow.row_number).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def count_rows(self, upload_id: UUID, status: str | None = None) -> int:
        """Количество строк загрузки (с учётом фильтра по статусу)."""
        statement = select(func.count()).select_from(SpecificationRow).where(
            SpecificationRow.upload_id == upload_id
        )
        if status:
            statement = statement.where(SpecificationRow.status == status)
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def count_rows_by_status(self, upload_id: UUID) -> dict[str, int]:
        """Счётчик строк загрузки по статусам (для сводки в карточке спецификации)."""
        result = await self._session.execute(
            select(SpecificationRow.status, func.count())
            .where(SpecificationRow.upload_id == upload_id)
            .group_by(SpecificationRow.status)
        )
        return {
            (status.value if hasattr(status, "value") else str(status)): int(count)
            for status, count in result.all()
        }

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
