"""Репозиторий каталога: чтение номенклатуры и пакетная запись из прайс-листов."""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CatalogItem


class CatalogRepository:
    """Доступ к номенклатуре каталога (таблица catalog_items)."""

    # Колонки уникального индекса uq_catalog_items_sku_name — цель ON CONFLICT при UPSERT
    UPSERT_INDEX_ELEMENTS = ("sku", "name")

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_items(self, search: str | None = None, offset: int = 0, limit: int = 50) -> list[CatalogItem]:
        """Страница позиций каталога; поиск — по наименованию и артикулу (подстрока)."""
        statement = select(CatalogItem)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(CatalogItem.name.ilike(pattern), CatalogItem.sku.ilike(pattern))
            )
        statement = statement.order_by(CatalogItem.name).offset(offset).limit(limit)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def count_items(self, search: str | None = None) -> int:
        """Количество позиций каталога с учётом поиска (для пагинации)."""
        statement = select(func.count()).select_from(CatalogItem)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(CatalogItem.name.ilike(pattern), CatalogItem.sku.ilike(pattern))
            )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def upsert_batch(self, items: list[dict[str, Any]]) -> int:
        """Пакетный UPSERT позиций каталога по уникальной паре (sku, name).

        Повторная загрузка прайс-листа (или прайса с пересекающейся номенклатурой)
        обновляет цену/единицу/эмбеддинг существующей позиции вместо попытки
        вставить дубликат, которая упёрлась бы в уникальный индекс.

        Args:
            items: список dict с ключами sku, name и необязательными unit, price, embedding.

        Returns:
            Количество обработанных строк.
        """
        if not items:
            return 0

        statement = pg_insert(CatalogItem).values(items)
        statement = statement.on_conflict_do_update(
            index_elements=list(self.UPSERT_INDEX_ELEMENTS),
            set_={
                "unit": statement.excluded.unit,
                "price": statement.excluded.price,
                "embedding": statement.excluded.embedding,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        return len(items)
