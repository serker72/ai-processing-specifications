"""Pydantic-схемы fingerprint-устройств (панель администратора)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceItem(BaseModel):
    """Зарегистрированное устройство."""

    model_config = ConfigDict(from_attributes=True)

    fingerprint_hash: str = Field(..., description="SHA-256 хэш fingerprint устройства")
    blocked: bool = Field(..., description="Заблокирован ли вход с устройства")
    first_seen_at: datetime = Field(..., description="Время первого входа с устройства")
    last_seen_at: datetime = Field(..., description="Время последнего входа с устройства")


class DeviceListResponse(BaseModel):
    """Список устройств."""

    devices: list[DeviceItem]


class DeviceBlockUpdate(BaseModel):
    """Блокировка/разблокировка устройства."""

    blocked: bool = Field(..., description="true — заблокировать вход, false — разблокировать")
