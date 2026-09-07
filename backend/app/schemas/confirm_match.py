"""Pydantic-схемы для подтверждения совпадений Matching Engine (Модуль 4)."""

from pydantic import BaseModel, Field


class ConfirmMatchRequest(BaseModel):
    """Запрос на подтверждение совпадения строки спецификации с каталогом."""

    raw_name: str = Field(..., description="Исходное наименование из спецификации")
    catalog_item_id: str = Field(..., description="Идентификатор подтверждённой позиции каталога")
    tier: str = Field(..., description="Tier матчинга (auto, top_n, unmatched)")


class ConfirmMatchResponse(BaseModel):
    """Ответ на подтверждение совпадения."""

    raw_name: str
    catalog_item_id: str
    tier: str
    saved: bool
    message: str
