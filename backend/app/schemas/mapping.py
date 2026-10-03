"""Pydantic-схемы для задач анализа прайс-листов (Модуль 3 и 5)."""

from typing import Any

from pydantic import BaseModel, Field


class ColumnMappingPrediction(BaseModel):
    """Предсказание ролей колонок прайс-листа, возвращаемое LLM."""

    sku_column: str = Field(..., description="Имя колонки с артикулом/SKU")
    name_column: str = Field(..., description="Имя колонки с наименованием товара")
    price_column: str | None = Field(None, description="Имя колонки с ценой (если есть)")
    unit_column: str | None = Field(None, description="Имя колонки с единицей измерения (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")

    @staticmethod
    def _as_column(value: Any, valid_columns: set[str] | None) -> str | None:
        """Привести значение LLM к имени существующей колонки (или None).

        Модель нередко отвечает не по схеме: вместо имени колонки отдаёт
        объект (например, когда ценовых колонок несколько) или меняет местами
        имя и роль. Поэтому: у объекта берём первое строковое значение,
        результат проверяем по списку реальных колонок файла.
        """
        if isinstance(value, dict):
            for candidate in value.values():
                resolved = ColumnMappingPrediction._as_column(candidate, valid_columns)
                if resolved:
                    return resolved
            return None
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value:
            return None
        if valid_columns is not None and value not in valid_columns:
            return None
        return value

    @classmethod
    def from_llm_response(
        cls, response: dict[str, Any], valid_columns: set[str] | None = None
    ) -> "ColumnMappingPrediction":
        """Конвертация ответа LLM в Pydantic-схему с устойчивостью к отклонениям.

        `valid_columns` — имена колонок файла: всё, что не совпало с реальной
        колонкой, отбрасывается, чтобы подтверждение маппинга не падало на
        несуществующей колонке. Роли `sku_column`/`name_column` остаются
        строками (возможно пустыми) — их отсутствие валидирует админ в UI.
        """
        response = dict(response)
        additional_raw = response.pop("additional_columns", None) or {}

        additional: dict[str, str] = {}
        if isinstance(additional_raw, dict):
            for key, value in additional_raw.items():
                column = cls._as_column(key, valid_columns)
                role = value
                if column is None:
                    # Модель перепутала местами имя колонки и роль.
                    column = cls._as_column(value, valid_columns)
                    role = key
                if column is not None:
                    role_text = "" if role is None else str(role).strip()
                    if role_text:
                        additional[column] = role_text

        sku_column = cls._as_column(response.get("sku_column"), valid_columns) or ""
        name_column = cls._as_column(response.get("name_column"), valid_columns) or ""
        price_column = cls._as_column(response.get("price_column"), valid_columns)
        unit_column = cls._as_column(response.get("unit_column"), valid_columns)

        # Колонка с основной ролью не может быть ещё и дополнительной.
        for main_column in (sku_column, name_column, price_column, unit_column):
            if main_column:
                additional.pop(main_column, None)

        return cls(
            sku_column=sku_column,
            name_column=name_column,
            price_column=price_column,
            unit_column=unit_column,
            additional_columns=additional,
        )
