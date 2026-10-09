"""Репозиторий каталога: чтение номенклатуры и пакетная запись из прайс-листов."""

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CatalogItem


def content_hash_of(sku: str, name: str) -> str:
    """SHA-256 хэш содержимого позиции (sku + name).

    Эмбеддинг строится по паре sku + name, поэтому совпадение хэша означает,
    что пересчёт эмбеддинга не нужен (проблема 3: пропуск неизменных строк
    при повторной векторизации каталога).
    """
    return hashlib.sha256(f"{sku}\n{name}".encode()).hexdigest()


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

    async def get_by_id(self, item_id: uuid.UUID) -> CatalogItem | None:
        """Позиция каталога по ID."""
        return await self._session.get(CatalogItem, item_id)

    async def update(self, item: CatalogItem, values: dict[str, Any]) -> CatalogItem:
        """Обновить переданные поля позиции каталога."""
        for field, value in values.items():
            setattr(item, field, value)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def commit(self) -> None:
        """Зафиксировать правку до постановки Celery-таски пересчёта эмбеддинга.

        Иначе воркер может выбрать задачу раньше, чем unit-of-work запроса
        завершится коммитом, и не найти позицию в базе.
        """
        await self._session.commit()

    async def rollback(self) -> None:
        """Откатить транзакцию после ошибки (например, нарушения уникальности).

        Иначе сессия остаётся в состоянии PendingRollbackError и падает
        уже на teardown dishka при попытке коммита.
        """
        await self._session.rollback()

    async def find_hashes_by_keys(
        self, keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        """Получить существующие content_hash для пар (sku, name).

        Возвращает словарь {(sku, name): content_hash} только для строк,
        у которых уже есть хэш (не NULL) — используется для определения
        строк, не требующих пересчёта эмбеддинга (проблема 3).
        """
        if not keys:
            return {}
        statement = (
            select(CatalogItem.sku, CatalogItem.name, CatalogItem.content_hash)
            .where(
                CatalogItem.content_hash.is_not(None),
                tuple_(CatalogItem.sku, CatalogItem.name).in_(keys),
            )
        )
        result = await self._session.execute(statement)
        return {(row.sku, row.name): row.content_hash for row in result}

    async def upsert_batch(self, items: list[dict[str, Any]]) -> int:
        """Пакетный UPSERT позиций каталога по уникальной паре (sku, name).

        Повторная загрузка прайс-листа (или прайса с пересекающейся номенклатурой)
        обновляет цену/единицу/эмбеддинг существующей позиции вместо попытки
        вставить дубликат, которая упёрлась бы в уникальный индекс.

        Для строк с ``embedding = None`` (неизменённые позиции при повторной
        векторизации) старый эмбеддинг сохраняется через ``COALESCE``, а
        ``DO UPDATE`` выполняется только если ``price``, ``unit`` или
        ``content_hash`` реально изменились — это предотвращает лишнюю
        переиндексацию HNSW-индекса для тысяч unchanged-строк.

        Args:
            items: список dict с ключами sku, name и необязательными
                   unit, price, embedding, content_hash.

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
                "embedding": func.coalesce(
                    statement.excluded.embedding, CatalogItem.embedding
                ),
                "content_hash": statement.excluded.content_hash,
                "updated_at": func.now(),
            },
            where=or_(
                CatalogItem.price.is_distinct_from(statement.excluded.price),
                CatalogItem.unit.is_distinct_from(statement.excluded.unit),
                CatalogItem.content_hash.is_distinct_from(
                    statement.excluded.content_hash
                ),
            ),
        )
        await self._session.execute(statement)
        return len(items)
