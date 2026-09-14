"""Pydantic-схемы серверных сессий (панель администратора)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.models import UserRole


class SessionItem(BaseModel):
    """Активная сессия: пользователь, устройство и срок жизни refresh-токена."""

    id: str = Field(..., description="Id сессии: user_id:fingerprint_hash (ключ сессии в Redis)")
    user_id: str = Field(..., description="Идентификатор пользователя")
    email: str = Field(..., description="Email пользователя (пустой, если пользователь удалён)")
    role: UserRole | None = Field(None, description="Роль пользователя (None, если пользователь удалён)")
    fingerprint_hash: str = Field(..., description="SHA-256 хэш fingerprint устройства")
    started_at: datetime | None = Field(
        None, description="Время выдачи refresh-токена сессии (время последнего обновления токенов)"
    )
    expires_at: datetime = Field(..., description="Время истечения сессии (TTL refresh-токена)")


class SessionListResponse(BaseModel):
    """Список активных сессий."""

    sessions: list[SessionItem]
