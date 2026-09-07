"""Сервис матчинга: трёхуровневый алгоритм сопоставления строк спецификации с каталогом.

Tier 1 (AUTO): точное совпадение по SHA-256 хэшу в HistoricalMatch — O(1).
Tier 2 (TOP_N): векторный поиск через pgvector `<=>` — топ-N кандидатов.
Tier 3 (UNMATCHED): если нет кандидатов с достаточной схожестью.
"""

from app.repositories.matching_repository import MatchingRepository
from app.services.embedding_service import EmbeddingService


class MatchingService:
    """Трёхуровневый Matching Engine для сопоставления строк спецификации с каталогом."""

    TIER2_LIMIT = 5
    TIER2_MIN_SCORE = 0.70

    def __init__(
        self,
        matching_repo: MatchingRepository,
        embedding_service: EmbeddingService,
    ) -> None:
        self._matching_repo = matching_repo
        self._embedding_service = embedding_service

    async def match_row(self, raw_name: str, sku: str | None = None) -> dict:
        """Выполнить трёхуровневый матчинг строки спецификации.

        Args:
            raw_name: исходное наименование из строки спецификации.
            sku: артикул из строки спецификации (опционально, пока не используется).

        Returns:
            {
                "tier": "auto" | "top_n" | "unmatched",
                "raw_name": "...",
                "matched_item": {...} | None,
                "candidates": [...],  # для Tier 2
                "score": float | None,
            }
        """
        # === Tier 1: точное совпадение по словарю HistoricalMatch ===
        match = await self._matching_repo.find_by_hash(raw_name)
        if match:
            return {
                "tier": "auto",
                "raw_name": raw_name,
                "matched_item": {
                    "id": str(match.catalog_item.id),
                    "sku": match.catalog_item.sku,
                    "name": match.catalog_item.name,
                    "unit": match.catalog_item.unit,
                    "price": match.catalog_item.price,
                },
                "candidates": [],
                "score": 1.0,
            }

        # === Tier 2: векторный поиск ===
        embedding = self._embedding_service.embed_query(raw_name)
        candidates = await self._matching_repo.find_top_n(
            embedding,
            limit=self.TIER2_LIMIT,
            min_score=self.TIER2_MIN_SCORE,
        )

        if candidates:
            best_item, best_distance = candidates[0]
            best_similarity = 1.0 - best_distance

            return {
                "tier": "top_n",
                "raw_name": raw_name,
                "matched_item": {
                    "id": str(best_item.id),
                    "sku": best_item.sku,
                    "name": best_item.name,
                    "unit": best_item.unit,
                    "price": best_item.price,
                },
                "candidates": [
                    {
                        "id": str(item.id),
                        "sku": item.sku,
                        "name": item.name,
                        "unit": item.unit,
                        "price": item.price,
                        "similarity": round(1.0 - distance, 4),
                    }
                    for item, distance in candidates
                ],
                "score": best_similarity,
            }

        # === Tier 3: не найдено ===
        return {
            "tier": "unmatched",
            "raw_name": raw_name,
            "matched_item": None,
            "candidates": [],
            "score": None,
        }

    async def confirm_match(self, raw_name: str, catalog_item_id: str, tier: str) -> dict:
        """Подтвердить совпадение и сохранить в HistoricalMatch (Tier-1 словарь).

        После подтверждения строка будет мгновенно находиться по Tier 1 при следующем запросе.
        """
        from uuid import UUID

        saved = await self._matching_repo.confirm_match(raw_name, UUID(catalog_item_id))

        return {
            "raw_name": raw_name,
            "catalog_item_id": catalog_item_id,
            "tier": tier,
            "saved": saved,
            "message": "Совпадение сохранено в словарь подтверждённых совпадений (Tier-1)" if saved else "Ошибка сохранения",
        }
