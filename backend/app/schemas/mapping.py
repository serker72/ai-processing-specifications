"""Pydantic-схемы для задач анализа прайс-листов (Модуль 3 и 5)."""

from typing import Any

from pydantic import BaseModel, Field


class ColumnMappingPrediction(BaseModel):
    """Предсказание ролей колонок прайс-листа, возвращаемое LLM."""

    sku_column: str = Field(..., description="Имя колонки с артикулом/SKU")
    name_column: str = Field(..., description="Имя колонки с наименованием товара")
    price_column: str | None = Field(None, description="Имя колонки с ценой (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")

    @classmethod
    def from_llm_response(cls, response: dict[str, Any]) -> "ColumnMappingPrediction":
        """Конвертация ответа LLM в Pydantic-схему."""
        additional = response.pop("additional_columns", {})
        return cls(**response, additional_columns=additional)
