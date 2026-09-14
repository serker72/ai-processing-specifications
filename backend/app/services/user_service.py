"""Сервис управления пользователями (панель администратора)."""

import uuid

from fastapi import HTTPException, status

from app.core.messages import AuthMessages, UserMessages
from app.models.models import User, UserRole
from app.repositories.user_repository import UserRepository


class UserService:
    """Чтение списка пользователей и изменение ролей."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    async def list_users(self) -> list[User]:
        """Список всех пользователей (новые — первыми)."""
        return await self._user_repository.list_all()

    async def update_role(self, *, current_user: User, user_id: uuid.UUID, role: UserRole) -> User:
        """Изменить роль пользователя.

        Собственную роль менять нельзя: администратор, снявший с себя роль,
        теряет доступ к панели и не может вернуть её себе обратно.
        """
        if current_user.id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.ROLE_SELF_CHANGE
            )

        user = await self._user_repository.get_by_id(str(user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)

        if user.role == role:
            return user

        return await self._user_repository.update_role(user, role)
