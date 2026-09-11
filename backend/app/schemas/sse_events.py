"""Pydantic-схемы для SSE-событий обработки спецификации (Модуль 5)."""

from pydantic import BaseModel, Field


class RowMatchEvent(BaseModel):
    """Событие обработки одной строки спецификации."""

    upload_id: str
    row_number: int
    raw_name: str
    matched_item_id: str | None = Field(None, description="Идентификатор найденного товара каталога")
    match_type: str | None = Field(None, description="Тип матчинга: auto / top_n / unmatched")
    status: str = Field(..., description="Статус строки: matched / unmatched")
    score: float | None = Field(None, description="Схожесть (cosine similarity)")
    message: str = Field(..., description="Сообщение о результате обработки")


class ProgressEvent(BaseModel):
    """Событие прогресса обработки спецификации."""

    upload_id: str
    processed: int
    total: int
    status: str = Field(..., description="pending / processing / completed / error")
    message: str = Field(..., description="Сообщение о статусе")
