"""Pydantic-схемы для запросов и ответов Matching Engine (Модуль 4)."""

from typing import Any

from pydantic import BaseModel, Field


class MatchRequest(BaseModel):
    """Запрос на сопоставление строки спецификации с каталогом."""

    raw_name: str = Field(..., description="Исходное наименование из строки спецификации")
    sku: str | None = Field(None, description="Артикул из строки спецификации (опционально)")


class MatchCandidate(BaseModel):
    """Кандидат из векторного поиска (Tier 2)."""

    id: str
    sku: str
    name: str
    unit: str | None
    price: float | None
    similarity: float


class MatchResult(BaseModel):
    """Результат трёхуровневого матчинга."""

    tier: str = Field(..., description="Tier: auto, top_n, unmatched")
    raw_name: str = Field(..., description="Исходное наименование")
    matched_item: dict[str, Any] | None = Field(None, description="Сопоставленная позиция каталога")
    candidates: list[MatchCandidate] = Field(default_factory=list, description="Кандидаты из векторного поиска")
    score: float | None = Field(None, description="Схожесть (cosine similarity) лучшего кандидата")


class MatchResponse(BaseModel):
    """Ответ на запрос матчинга."""

    result: MatchResult
