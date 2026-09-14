"""Pydantic-схемы для предсказания маппинга колонок спецификации (Модуль 5)."""

from datetime import datetime

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


class SpecificationUploadItem(BaseModel):
    """Элемент списка ранее загруженных спецификаций."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    status: str = Field(..., description="Статус обработки файла")
    created_at: datetime = Field(..., description="Время загрузки")


class SpecificationUploadListResponse(BaseModel):
    """Ответ со списком загрузок спецификаций менеджера."""

    uploads: list[SpecificationUploadItem]


class SpecificationUploadDetail(BaseModel):
    """Карточка спецификации: файл, стадия обработки, маппинг, сводка по строкам."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    status: str = Field(..., description="Статус обработки файла (UploadStatus)")
    created_at: datetime = Field(..., description="Время загрузки")
    column_mapping: dict | None = Field(None, description="Подтверждённый маппинг колонок")
    rows_total: int = Field(..., description="Всего строк в загрузке")
    rows_by_status: dict[str, int] = Field(
        default_factory=dict, description="Счётчик строк по статусам RowStatus"
    )


class MatchedCatalogItem(BaseModel):
    """Позиция каталога, сопоставленная строке спецификации."""

    id: str = Field(..., description="Идентификатор позиции каталога")
    sku: str = Field(..., description="Артикул (SKU)")
    name: str = Field(..., description="Наименование позиции")
    unit: str | None = Field(None, description="Единица измерения")
    price: float | None = Field(None, description="Цена за единицу")


class SpecificationRowItem(BaseModel):
    """Строка спецификации с результатом матчинга."""

    id: str = Field(..., description="Идентификатор строки")
    row_number: int = Field(..., description="Порядковый номер строки в файле")
    raw_name: str = Field(..., description="Наименование из файла клиента")
    quantity: float | None = Field(None, description="Количество из файла клиента")
    unit: str | None = Field(None, description="Единица измерения из файла клиента")
    price: float | None = Field(None, description="Цена из файла клиента (если была)")
    match_type: str | None = Field(None, description="Тип матчинга: auto / top_n / unmatched")
    status: str = Field(..., description="Статус строки (RowStatus)")
    matched_item: MatchedCatalogItem | None = Field(None, description="Сопоставленная позиция каталога")


class SpecificationRowListResponse(BaseModel):
    """Ответ со страницей строк спецификации."""

    rows: list[SpecificationRowItem]
    total: int = Field(..., description="Всего строк с учётом фильтра")
    page: int = Field(..., description="Номер страницы")
    page_size: int = Field(..., description="Размер страницы")
