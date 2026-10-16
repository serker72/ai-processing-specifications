"""Pydantic-схемы для предсказания маппинга колонок спецификации (Модуль 5)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SpecificationMappingPrediction(BaseModel):
    """Предсказание ролей колонок спецификации от LLM."""

    name_column: str = Field(..., description="Колонка с наименованием товара")
    quantity_column: str | None = Field(None, description="Колонка с количеством (если есть)")
    unit_column: str | None = Field(None, description="Колонка с единицей измерения (если есть)")
    price_column: str | None = Field(None, description="Колонка с ценой (если есть)")
    additional_columns: dict[str, str] = Field(default_factory=dict, description="Доп. колонки: {имя_колонки: роль}")

    @classmethod
    def from_llm_response(
        cls, response: dict, valid_columns: set[str] | None = None
    ) -> "SpecificationMappingPrediction":
        """Создать объект из ответа LLM с валидацией имён колонок.

        Имена возвращаются СТРОГО как в заголовках файла: LLM часто отдаёт их в
        другом регистре/с лишними пробелами, а frontend сопоставляет значения со
        списком `<option>` по точному совпадению — иначе селекты пустые.

        Если LLM вернул имя, которого нет в файле — берётся ближайший вариант из
        `valid_columns` (по вхождению подстроки) или `None`.
        """
        from app.services.excel_preview_service import ExcelPreviewService

        # нормализованное имя -> оригинальный заголовок из файла
        by_norm: dict[str, str] = (
            {ExcelPreviewService.normalize_title(c): c for c in valid_columns}
            if valid_columns
            else {}
        )

        def resolve(value: object) -> str | None:
            if not isinstance(value, str) or not value.strip():
                return None
            if not by_norm:
                return value
            normalized = ExcelPreviewService.normalize_title(value)
            exact = by_norm.get(normalized)
            if exact is not None:
                return exact
            # Нечёткое совпадение: LLM вернул часть заголовка или добавил текст
            for norm, original in by_norm.items():
                if normalized in norm or norm in normalized:
                    return original
            return None

        name_col = resolve(response.get("name_column")) or ""
        quantity_col = resolve(response.get("quantity_column"))
        unit_col = resolve(response.get("unit_column"))
        price_col = resolve(response.get("price_column"))

        additional: dict[str, str] = {}
        for key, value in response.items():
            if key in ("name_column", "quantity_column", "unit_column", "price_column"):
                continue
            if isinstance(value, str):
                resolved = resolve(value)
                if resolved is not None:
                    additional[key] = resolved

        return cls(
            name_column=name_col,
            quantity_column=quantity_col,
            unit_column=unit_col,
            price_column=price_col,
            additional_columns=additional,
        )


class SpecificationUploadItem(BaseModel):
    """Элемент списка ранее загруженных спецификаций."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    status: str = Field(..., description="Статус обработки файла")
    created_at: datetime = Field(..., description="Время загрузки")
    client_id: str = Field(..., description="Идентификатор клиента (покупателя)")
    client_name: str | None = Field(None, description="Наименование клиента")


class SpecificationUploadListResponse(BaseModel):
    """Ответ со списком загрузок спецификаций менеджера."""

    uploads: list[SpecificationUploadItem]


class SpecificationUploadDetail(BaseModel):
    """Карточка спецификации: файл, стадия обработки, маппинг, сводка по строкам."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    status: str = Field(..., description="Статус обработки файла (UploadStatus)")
    created_at: datetime = Field(..., description="Время загрузки")
    client_id: str = Field(..., description="Идентификатор клиента (покупателя)")
    client_name: str | None = Field(None, description="Наименование клиента")
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
    is_overridden: bool = Field(False, description="Флаг: выбор менеджера отличается от автосопоставления")
    snapshot_item_name: str | None = Field(None, description="Снапшот наименования на момент матчинга")
    snapshot_sku: str | None = Field(None, description="Снапшот артикула на момент матчинга")
    snapshot_price: float | None = Field(None, description="Снапшот цены на момент матчинга")
    snapshot_unit: str | None = Field(None, description="Снапшот единицы на момент матчинга")


class SpecificationRowListResponse(BaseModel):
    """Ответ со страницей строк спецификации."""

    rows: list[SpecificationRowItem]
    total: int = Field(..., description="Всего строк с учётом фильтра")
    page: int = Field(..., description="Номер страницы")
    page_size: int = Field(..., description="Размер страницы")


class RowStatusUpdateRequest(BaseModel):
    """Смена статуса строки менеджером: подтвердить, исключить или вернуть в обработку."""

    status: Literal["confirmed", "excluded", "unmatched"] = Field(..., description="Новый статус строки (RowStatus)")
    catalog_item_id: str | None = Field(
        None, description="Позиция каталога для подтверждения (по умолчанию — уже сопоставленная)"
    )


class RowMatchCandidate(BaseModel):
    """Кандидат из векторного поиска для выбора менеджером."""

    id: str = Field(..., description="Идентификатор позиции каталога")
    sku: str = Field(..., description="Артикул (SKU)")
    name: str = Field(..., description="Наименование позиции")
    unit: str | None = Field(None, description="Единица измерения")
    price: float | None = Field(None, description="Цена за единицу")
    similarity: float = Field(..., description="Косинусная схожесть с наименованием строки")


class RowMatchesResponse(BaseModel):
    """Топ-N кандидатов векторного поиска для строки спецификации."""

    row_id: str = Field(..., description="Идентификатор строки")
    raw_name: str = Field(..., description="Наименование строки из файла клиента")
    match_type: str | None = Field(None, description="Текущий тип матчинга строки")
    matched_item: MatchedCatalogItem | None = Field(None, description="Текущая сопоставленная позиция")
    candidates: list[RowMatchCandidate] = Field(default_factory=list, description="Кандидаты, упорядоченные по схожести")
