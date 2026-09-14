"""Репозиторий пользователей."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User, UserRole


class UserRepository:
    """Доступ к данным пользователей (таблица users)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        """Найти пользователя по email."""
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        """Найти пользователя по идентификатору."""
        result = await self._session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[User]:
        """Список всех пользователей (новые — первыми)."""
        result = await self._session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def update_role(self, user: User, role: UserRole) -> User:
        """Изменить роль пользователя."""
        user.role = role
        await self._session.flush()
        return user
