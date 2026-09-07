"""Pydantic-схемы для предсказания маппинга колонок спецификации (Модуль 5)."""

from pydantic import BaseModel, Field


class SpecificationMappingPrediction(BaseModel):
    """Предсказание ролей колонок спецификации от LLM."""

    name_column: str = Field(..., description="Колонка с наименованием товара")
    quantity_column: str | None = Field(None, description="Колонка с количеством (если есть)")
    unit_column: str | None = Field(None, description="Колонка с единицей измерения (если есть)")
    price_column: str | None = Field(None, description="Колонка с ценой (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")

    @classmethod
    def from_llm_response(cls, response: dict) -> "SpecificationMappingPrediction":
        """Создать объект из ответа LLM с валидацией."""
        additional: dict[str, str] = {}
        # Дополнительные колонки — те, что НЕ вошли в основные поля
        for key, value in response.items():
            if key in ("name_column", "quantity_column", "unit_column", "price_column"):
                continue
            if isinstance(value, str):
                additional[key] = value

        return cls(
            name_column=response.get("name_column", ""),
            quantity_column=response.get("quantity_column"),
            unit_column=response.get("unit_column"),
            price_column=response.get("price_column"),
            additional_columns=additional,
        )
