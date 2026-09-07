"""Репозиторий для матчинга: Tier 1 (HistoricalMatch) и Tier 2 (векторный поиск CatalogItem)."""

import hashlib
import hmac
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import CatalogItem, HistoricalMatch


class MatchingRepository:
    """Поиск совпадений: словарь подтверждённых совпадений (Tier-1) и векторный поиск (Tier-2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_hash(self, raw_name: str) -> HistoricalMatch | None:
        """Tier 1: найти подтверждённое совпадение по SHA-256 хэшу наименования.

        O(1) lookup — уникальный индекс по raw_name_hash.
        """
        raw_name_hash = self._hash_name(raw_name)
        stmt = select(HistoricalMatch).where(
            HistoricalMatch.raw_name_hash == raw_name_hash
        ).options(selectinload(HistoricalMatch.catalog_item))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_top_n(
        self,
        embedding: list[float],
        limit: int = 5,
        min_score: float = 0.70,
    ) -> list[tuple[CatalogItem, float]]:
        """Tier 2: векторный поиск k ближайших соседей по косинусной дистанции.

        Использует HNSW-индекс `<=>` operator на поле embedding.
        Возвращает список пар (catalog_item, cosine_distance), отсортированных по возрастанию дистанции.
        Отфильтровывает результаты с дистанцией >= min_score (т.е. cosine similarity < min_score).
        """
        # Используем pgvector.cosine_distance() для корректной работы с SQLAlchemy
        distance = CatalogItem.embedding.cosine_distance(embedding)
        stmt = (
            select(CatalogItem, distance.label("distance"))
            .order_by(distance)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        # distance = 1 - cosine_similarity, поэтому distance < (1 - min_score) => similarity > min_score
        threshold = 1.0 - min_score
        return [(row[0], float(row[1])) for row in rows if row[1] < threshold]

    @staticmethod
    def _hash_name(raw_name: str) -> str:
        """Вычислить SHA-256 хэш строки (hex)."""
        return hmac.new(
            b"match_salt",
            raw_name.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def confirm_match(self, raw_name: str, catalog_item_id: UUID) -> bool:
        """Сохранить подтверждённое совпадение в HistoricalMatch (Tier-1 словарь).

        Если запись уже существует — обновляет. Возвращает True, если запись создана/обновлена.
        """
        raw_name_hash = self._hash_name(raw_name)
        existing = await self.find_by_hash(raw_name)
        if existing:
            existing.catalog_item_id = catalog_item_id
            await self._session.flush()
            return True

        match = HistoricalMatch(
            raw_name_hash=raw_name_hash,
            raw_name=raw_name,
            catalog_item_id=catalog_item_id,
        )
        self._session.add(match)
        await self._session.flush()
        return True
