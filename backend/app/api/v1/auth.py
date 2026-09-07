"""Эндпоинты авторизации (Модуль 2).

Обработчики только принимают запрос и вызывают сервис; зависимости внедряются
через dishka (route_class=DishkaRoute). Токены передаются только через
HttpOnly-куки.
"""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import Settings
from app.core.messages import AuthMessages
from app.schemas.auth import LoginRequest, RefreshRequest
from app.services.auth_service import AuthService

router = APIRouter(route_class=DishkaRoute)


def _get_cookie(request: Request, settings: Settings, name: str) -> str:
    """Прочитать HttpOnly-куку с токеном (пустая строка, если куки нет)."""
    return request.cookies.get(getattr(settings.jwt, name), "")


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    payload: LoginRequest,
    response: Response,
    auth_service: FromDishka[AuthService],
) -> None:
    """Аутентификация по email/паролю с привязкой токенов к fingerprint."""
    await auth_service.login(payload, response)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    auth_service: FromDishka[AuthService],
    settings: FromDishka[Settings],
) -> None:
    """Обновление пары токенов: ротация refresh-токена, старые jti — в blacklist."""
    refresh_token = _get_cookie(request, settings, "refresh_cookie_name")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.REFRESH_TOKEN_MISSING)
    access_token = _get_cookie(request, settings, "access_cookie_name")
    await auth_service.refresh(access_token, refresh_token, payload.fingerprint, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth_service: FromDishka[AuthService],
    settings: FromDishka[Settings],
) -> None:
    """Выход: jti токенов — в blacklist, сессия удаляется, куки очищаются."""
    access_token = _get_cookie(request, settings, "access_cookie_name")
    refresh_token = _get_cookie(request, settings, "refresh_cookie_name")
    await auth_service.logout(access_token, refresh_token, response)
