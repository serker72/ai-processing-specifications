"""Pydantic-схемы загрузок прайс-листов (панель администратора)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PriceListUploadItem(BaseModel):
    """Элемент истории загрузок прайс-листов."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    admin_email: str = Field("", description="Email администратора, загрузившего файл")
    status: str = Field(..., description="Статус обработки файла")
    created_at: datetime = Field(..., description="Время загрузки")


class PriceListListResponse(BaseModel):
    """Список загрузок прайс-листов + счётчики по статусам."""

    uploads: list[PriceListUploadItem]

    # Считаются по всем загрузкам, а не по отфильтрованным; ключ — значение
    # UploadStatus. Статусов с нулём загрузок здесь нет (добавляет сервис).
    counts: dict[str, int] = Field(default_factory=dict, description="Загрузок в каждом статусе")


class PriceListPreviewResponse(BaseModel):
    """Превью прайс-листа для подтверждения маппинга колонок.

    rows — первые PREVIEW_ROWS строк данных (без заголовка); значения приходят
    из openpyxl как есть (число, дата, строка, None).
    """

    upload_id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    status: str = Field(..., description="Статус обработки файла")
    sheets: list[str] = Field(default_factory=list, description="Имена листов книги")
    headers: list[str] = Field(default_factory=list, description="Заголовки колонок первого листа")
    rows: list[list[Any]] = Field(default_factory=list, description="Строки превью")
    total_rows: int = Field(0, description="Всего строк данных в превью (с учётом лимита)")
    column_mapping: dict[str, Any] | None = Field(None, description="Сохранённый маппинг колонок")
