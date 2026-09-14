"""Эндпоинты администратора: пользователи, устройства и сессии (Модуль 2, задача 6.2).

Важно: dishka обрабатывает FromDishka[T] только в параметрах эндпоинта,
поэтому авторизация выполняется вызовом helpers из app.api.deps внутри
обработчика, а не через вложенные Depends.
"""

import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import get_current_admin
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.models.models import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.device import DeviceBlockUpdate, DeviceItem, DeviceListResponse
from app.schemas.session import SessionListResponse
from app.schemas.user import UserListResponse, UserResponse, UserRoleUpdate
from app.services.device_service import DeviceService
from app.services.security import SecurityService
from app.services.session_admin_service import SessionAdminService
from app.services.user_service import UserService

admin_access_router = APIRouter(route_class=DishkaRoute, prefix="/admin", tags=["admin"])


@admin_access_router.get(
    "/users",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="Список пользователей",
)
async def list_users(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    user_service: FromDishka[UserService],
) -> UserListResponse:
    """Все пользователи системы (новые — первыми)."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    users = await user_service.list_users()
    return UserListResponse(users=[UserResponse.from_user(user) for user in users])


@admin_access_router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Изменить роль пользователя",
)
async def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    user_service: FromDishka[UserService],
) -> UserResponse:
    """Назначить пользователю роль admin или manager."""
    admin: User = await get_current_admin(request, settings, security_service, session_repository, user_repository)

    try:
        user = await user_service.update_role(
            current_user=admin, user_id=uuid.UUID(user_id), role=payload.role
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND) from None

    return UserResponse.from_user(user)


@admin_access_router.get(
    "/sessions",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="Активные сессии пользователей",
)
async def list_sessions(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    session_admin_service: FromDishka[SessionAdminService],
) -> SessionListResponse:
    """Сессии с активным refresh-токеном в Redis: пользователь, устройство, срок истечения."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    sessions = await session_admin_service.list_sessions()
    return SessionListResponse(sessions=sessions)


@admin_access_router.delete(
    "/sessions/{user_id}/{fingerprint_hash}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать сессию пользователя",
)
async def revoke_session(
    user_id: str,
    fingerprint_hash: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    session_admin_service: FromDishka[SessionAdminService],
) -> None:
    """Принудительный выход: удалить сессию и отозвать её refresh-токен."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    await session_admin_service.revoke_session(user_id, fingerprint_hash)


@admin_access_router.get(
    "/devices",
    response_model=DeviceListResponse,
    status_code=status.HTTP_200_OK,
    summary="Зарегистрированные fingerprint-устройства",
)
async def list_devices(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    device_service: FromDishka[DeviceService],
) -> DeviceListResponse:
    """Устройства, с которых выполнялся вход: отпечаток, статус, время последнего входа."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    devices = await device_service.list_devices()
    return DeviceListResponse(devices=[DeviceItem.model_validate(d) for d in devices])


@admin_access_router.patch(
    "/devices/{fingerprint_hash}",
    response_model=DeviceItem,
    status_code=status.HTTP_200_OK,
    summary="Заблокировать или разблокировать устройство",
)
async def update_device_block(
    fingerprint_hash: str,
    payload: DeviceBlockUpdate,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    device_service: FromDishka[DeviceService],
) -> DeviceItem:
    """Блокировка запрещает вход с устройства и отзывает его активные сессии."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    device = await device_service.set_blocked(fingerprint_hash, payload.blocked)
    return DeviceItem.model_validate(device)
