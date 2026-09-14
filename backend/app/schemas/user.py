"""Pydantic-схемы пользователя."""

from datetime import datetime

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


class UserResponse(BaseModel):
    """Элемент списка пользователей в панели администратора."""

    id: str
    email: str
    role: UserRole
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        """Собрать ответ из ORM-модели (id — строка для клиента)."""
        return cls(id=str(user.id), email=user.email, role=user.role, created_at=user.created_at)


class UserListResponse(BaseModel):
    """Список пользователей."""

    users: list[UserResponse]


class UserRoleUpdate(BaseModel):
    """Изменение роли пользователя."""

    role: UserRole
