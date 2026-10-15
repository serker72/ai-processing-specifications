"""Pydantic-схемы для предсказания маппинга колонок спецификации (Модуль 5)."""

import re
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

        Если LLM вернул имя, которого нет в файле — заменяет на ближайший
        вариант из `valid_columns` (по вхождению подстроки) или `None`.
        """

        @staticmethod
        def _resolve(value: str | None, valid: set[str] | None) -> str | None:
            if not value:
                return None
            if valid is not None and value in valid:
                return value
            if valid is not None:
                # Попытка найти по нечёткому вхождению (casefold, без лишних пробелов)
                normalized = re.sub(r"\s+", " ", value).casefold()
                for candidate in valid:
                    if normalized in re.sub(r"\s+", " ", candidate).casefold():
                        return candidate
            return None

        from app.services.excel_preview_service import ExcelPreviewService

        # Нормализованные ключи для сравнения
        norm_valid: set[str] | None = None
        if valid_columns:
            norm_valid = {
                ExcelPreviewService.normalize_title(c) for c in valid_columns
            }

        name_col = _resolve(response.get("name_column"), norm_valid) or ""
        quantity_col = _resolve(response.get("quantity_column"), norm_valid)
        unit_col = _resolve(response.get("unit_column"), norm_valid)
        price_col = _resolve(response.get("price_column"), norm_valid)

        additional: dict[str, str] = {}
        for key, value in response.items():
            if key in ("name_column", "quantity_column", "unit_column", "price_column"):
                continue
            if isinstance(value, str):
                resolved = _resolve(value, norm_valid)
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
