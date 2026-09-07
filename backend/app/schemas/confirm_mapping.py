"""Pydantic-схемы для подтверждения маппинга колонок (Модуль 3)."""

from typing import Any

from pydantic import BaseModel, Field


class ConfirmMappingRequest(BaseModel):
    """Запрос на подтверждение/редактирование маппинга колонок."""

    sku_column: str = Field(..., description="Имя колонки с артикулом/SKU")
    name_column: str = Field(..., description="Имя колонки с наименованием товара")
    price_column: str | None = Field(None, description="Имя колонки с ценой (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")


class ConfirmMappingResponse(BaseModel):
    """Ответ на подтверждение маппинга."""

    upload_id: str
    status: str
    mapping: dict[str, Any]
