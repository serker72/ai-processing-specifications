"""Pydantic-схемы для подтверждения маппинга колонок спецификации (Модуль 5)."""

from typing import Any

from pydantic import BaseModel, Field


class ConfirmSpecificationMappingRequest(BaseModel):
    """Запрос на подтверждение/редактирование маппинга колонок спецификации."""

    name_column: str = Field(..., description="Имя колонки с наименованием товара")
    quantity_column: str | None = Field(None, description="Имя колонки с количеством (если есть)")
    unit_column: str | None = Field(None, description="Имя колонки с единицей измерения (если есть)")
    price_column: str | None = Field(None, description="Имя колонки с ценой (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")


class ConfirmSpecificationMappingResponse(BaseModel):
    """Ответ на подтверждение маппинга."""

    upload_id: str
    status: str
    mapping: dict[str, Any]


class MappingPreviewResponse(BaseModel):
    """Предпросмотр маппинга: заголовки колонок файла + предсказание LLM."""

    upload_id: str
    status: str
    headers: list[str] = Field(default_factory=list, description="Заголовки колонок из файла")
    mapping: dict[str, Any] = Field(default_factory=dict, description="Предсказанный маппинг колонок")
