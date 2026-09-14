"""Сервис каталога: чтение номенклатуры для панели администратора."""

from app.models.models import CatalogItem
from app.repositories.catalog_repository import CatalogRepository


class CatalogService:
    """Постраничное чтение позиций каталога."""

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
