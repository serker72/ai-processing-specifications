"""Pydantic-схемы каталога номенклатуры (панель администратора)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.models import CatalogItem


class CatalogItemResponse(BaseModel):
    """Позиция каталога."""

    id: str
    sku: str = Field(..., description="Артикул (SKU)")
    name: str = Field(..., description="Наименование позиции")
    unit: str | None = Field(None, description="Единица измерения")
    price: float | None = Field(None, description="Цена за единицу")
    created_at: datetime = Field(..., description="Время появления позиции в каталоге")

    @classmethod
    def from_item(cls, item: CatalogItem) -> "CatalogItemResponse":
        """Собрать ответ из ORM-модели (id — строка для клиента)."""
        return cls(
            id=str(item.id),
            sku=item.sku,
            name=item.name,
            unit=item.unit,
            price=item.price,
            created_at=item.created_at,
        )


class CatalogListResponse(BaseModel):
    """Страница позиций каталога."""

    items: list[CatalogItemResponse]
    total: int = Field(..., description="Всего позиций с учётом поиска")
    page: int = Field(..., description="Номер страницы (начинается с 1)")
    page_size: int = Field(..., description="Размер страницы")
