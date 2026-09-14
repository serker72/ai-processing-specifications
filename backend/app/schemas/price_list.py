"""Pydantic-схемы загрузок прайс-листов (панель администратора)."""

from datetime import datetime

from pydantic import BaseModel, Field


class PriceListUploadItem(BaseModel):
    """Элемент истории загрузок прайс-листов."""

    id: str = Field(..., description="Идентификатор сессии загрузки")
    filename: str = Field(..., description="Имя исходного Excel-файла")
    admin_email: str = Field("", description="Email администратора, загрузившего файл")
    status: str = Field(..., description="Статус обработки файла")
    created_at: datetime = Field(..., description="Время загрузки")


class PriceListListResponse(BaseModel):
    """Список загрузок прайс-листов."""

    uploads: list[PriceListUploadItem]
