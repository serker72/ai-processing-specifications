"""Сервис каталога: чтение номенклатуры для панели администратора."""

import uuid

from sqlalchemy.exc import IntegrityError

from app.core.messages import CatalogMessages
from app.models.models import CatalogItem
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import CatalogItemUpdate


class CatalogItemNotFoundError(LookupError):
    """Позиция каталога не найдена."""


class CatalogService:
    """Постраничное чтение и правка позиций каталога."""

    def __init__(self, catalog_repository: CatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    async def list_items(
        self, search: str | None = None, page: int = 1, page_size: int = 50
    ) -> tuple[list[CatalogItem], int]:
        """Страница позиций и общий размер выборки (для пагинации)."""
        offset = (page - 1) * page_size
        items = await self._catalog_repository.list_items(search=search, offset=offset, limit=page_size)
        total = await self._catalog_repository.count_items(search=search)
        return items, total

    async def update_item(
        self, item_id: uuid.UUID, payload: CatalogItemUpdate
    ) -> tuple[CatalogItem, bool]:
        """Обновить позицию каталога.

        Возвращает позицию и признак смены наименования: эмбеддинг строится по
        наименованию, поэтому при его правке воркер должен пересчитать вектор.

        Raises:
            CatalogItemNotFoundError: позиция не найдена.
        """
        item = await self._catalog_repository.get_by_id(item_id)
        if item is None:
            raise CatalogItemNotFoundError(CatalogMessages.NOT_FOUND)

        values = payload.model_dump(exclude_unset=True)
        # Наименование не может быть пустым (NOT NULL): явный null игнорируем.
        if values.get("name") is None:
            values.pop("name", None)
        name_changed = "name" in values and values["name"] != item.name

        try:
            item = await self._catalog_repository.update(item, values)
        except IntegrityError:
            # Нарушение уникальности (sku, name): откатываем транзакцию, чтобы
            # сессия осталась работоспособной для teardown dishka.
            await self._catalog_repository.rollback()
            raise
        return item, name_changed

    async def commit_item(self) -> None:
        """Зафиксировать правку до постановки фоновой таски пересчёта эмбеддинга."""
        await self._catalog_repository.commit()

