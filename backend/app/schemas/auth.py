"""Схемы эндпоинтов авторизации."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Тело запроса на логин."""

    email: EmailStr
    password: str = Field(min_length=1)
    # Клиентский хэш браузера от thumbmarkjs — привязывается к токенам
    fingerprint: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    """Тело запроса на обновление токенов (refresh-токен приходит из куки)."""

    fingerprint: str = Field(min_length=8, max_length=256)


class TokenPair(BaseModel):
    """Пара JWT-токенов (используется внутри сервиса, клиенту не отдаётся)."""

    access_token: str
    refresh_token: str
