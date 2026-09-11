"""Pydantic-схемы пользователя."""

from pydantic import BaseModel

from app.models.models import User, UserRole


class MeResponse(BaseModel):
    """Схема ответа с данными текущего пользователя (эндпоинт /auth/me)."""

    id: str
    email: str
    role: UserRole

    @classmethod
    def from_user(cls, user: User) -> "MeResponse":
        """Собрать ответ из ORM-модели (id — строка для клиента)."""
        return cls(id=str(user.id), email=user.email, role=user.role)
