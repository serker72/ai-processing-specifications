"""Зависимости FastAPI (авторизация защищённых эндпоинтов).

Важно: dishka обрабатывает FromDishka[T] только в параметрах самого эндпоинта,
поэтому функции здесь — обычные async-функции, вызываемые из эндпоинта с уже
разрешёнными зависимостями (не через Depends).
"""

import jwt as pyjwt
from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.core.messages import AuthMessages, CommonMessages
from app.models.models import User, UserRole
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.security import SecurityService


async def get_current_user(
    request: Request,
    settings: Settings,
    security_service: SecurityService,
    session_repository: SessionRepository,
    user_repository: UserRepository,
) -> User:
    """Авторизация по access-токену из куки с проверкой blacklist (revoked:{jti})."""
    token = request.cookies.get(settings.jwt.access_cookie_name, "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.TOKEN_MISSING)
    try:
        payload = security_service.decode_token(token, expected_type="access")
    except (pyjwt.PyJWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN) from None

    if await session_repository.is_jti_revoked(str(payload.get("jti"))):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.TOKEN_REVOKED)

    user = await user_repository.get_by_id(str(payload.get("sub")))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.USER_NOT_FOUND)
    return user


async def get_current_admin(
    request: Request,
    settings: Settings,
    security_service: SecurityService,
    session_repository: SessionRepository,
    user_repository: UserRepository,
) -> User:
    """Авторизация + проверка роли администратора."""
    user = await get_current_user(request, settings, security_service, session_repository, user_repository)
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CommonMessages.FORBIDDEN)
    return user


async def get_current_manager(
    request: Request,
    settings: Settings,
    security_service: SecurityService,
    session_repository: SessionRepository,
    user_repository: UserRepository,
) -> User:
    """Авторизация + проверка роли менеджера."""
    user = await get_current_user(request, settings, security_service, session_repository, user_repository)
    if user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CommonMessages.FORBIDDEN)
    return user
