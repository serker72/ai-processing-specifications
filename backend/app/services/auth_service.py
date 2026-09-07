"""Сервис авторизации: аутентификация, сессии (Redis), refresh и logout."""

from datetime import UTC, datetime

import jwt as pyjwt
from fastapi import HTTPException, Response, status

from app.core.config import Settings
from app.core.messages import AuthMessages
from app.models.models import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, TokenPair
from app.services.security import SecurityService

_TYPE_ACCESS = "access"
_TYPE_REFRESH = "refresh"


class AuthService:
    """Бизнес-логика авторизации: login / refresh / logout.

    Серверное состояние в Redis:
    - сессия session:{user_id}:{fp_hash} хранит активный refresh-токен;
    - blacklist revoked:{jti} — отозванные access/refresh токены.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        security_service: SecurityService,
        settings: Settings,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._security = security_service
        self._jwt_settings = settings.jwt

    async def login(self, payload: LoginRequest, response: Response) -> None:
        """Аутентифицировать пользователя, создать сессию и выставить токены в куки."""
        user = await self._authenticate(payload.email, payload.password)
        token_pair = self._security.create_token_pair(str(user.id), payload.fingerprint)
        await self._save_session(str(user.id), payload.fingerprint, token_pair)
        self._set_token_cookies(response, token_pair)

    async def refresh(self, access_token: str, refresh_token: str, fingerprint: str, response: Response) -> None:
        """Обновить пару токенов с ротацией: старые jti — в blacklist, сессия — перезаписана.

        Защита от угона сессии: проверяются подпись, тип, совпадение fingerprint
        и наличие сессии в Redis; использованный refresh-токен отзывается.
        """
        payload = self._decode_or_unauthorized(refresh_token, expected_type=_TYPE_REFRESH)

        fingerprint_hash = self._security.hash_fingerprint(fingerprint)
        if payload.get("fp") != fingerprint_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.FINGERPRINT_MISMATCH
            )

        user_id = str(payload.get("sub"))
        stored_token = await self._session_repository.get_session(user_id, fingerprint_hash)
        if stored_token is None or stored_token != refresh_token:
            # Сессия не найдена или refresh-токен устарел (уже ротирован/отозван)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.SESSION_NOT_FOUND
            )

        # Ротация: старые jti (access и refresh) — в blacklist
        await self._revoke_token_payload(payload)
        try:
            access_payload = self._security.decode_token(access_token, expected_type=_TYPE_ACCESS)
        except (pyjwt.PyJWTError, ValueError):
            access_payload = None
        if access_payload is not None:
            await self._revoke_token_payload(access_payload)

        token_pair = self._security.create_token_pair(user_id, fingerprint)
        await self._session_repository.save_session(
            user_id,
            fingerprint_hash,
            token_pair.refresh_token,
            ttl_seconds=self._refresh_ttl_seconds(),
        )
        self._set_token_cookies(response, token_pair)

    async def logout(self, access_token: str, refresh_token: str, response: Response) -> None:
        """Выйти: отозвать токены, удалить сессию и очистить куки."""
        for token, token_type in ((access_token, _TYPE_ACCESS), (refresh_token, _TYPE_REFRESH)):
            try:
                payload = self._security.decode_token(token, expected_type=token_type)
            except (pyjwt.PyJWTError, ValueError):
                continue
            await self._revoke_token_payload(payload)
            await self._session_repository.delete_session(str(payload.get("sub")), str(payload.get("fp")))
        self._clear_token_cookies(response)

    async def _authenticate(self, email: str, password: str) -> User:
        """Проверить учётные данные; при неудаче — 401 (без раскрытия деталей)."""
        user = await self._user_repository.get_by_email(email)
        # Единое сообщение, чтобы не раскрывать существование аккаунта
        if user is None or not self._security.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_CREDENTIALS
            )
        return user

    async def _save_session(self, user_id: str, fingerprint: str, token_pair: TokenPair) -> None:
        """Сохранить refresh-токен в Redis по ключу session:{user_id}:{fp_hash}."""
        fingerprint_hash = self._security.hash_fingerprint(fingerprint)
        await self._session_repository.save_session(
            user_id,
            fingerprint_hash,
            token_pair.refresh_token,
            ttl_seconds=self._refresh_ttl_seconds(),
        )

    async def _revoke_token_payload(self, payload: dict) -> None:
        """Отправить jti токена в blacklist с TTL = остаток жизни токена."""
        remaining = int(payload.get("exp", 0)) - int(datetime.now(UTC).timestamp())
        await self._session_repository.revoke_jti(str(payload.get("jti")), ttl_seconds=max(remaining, 0))

    def _refresh_ttl_seconds(self) -> int:
        """TTL refresh-токена/сессии в секундах."""
        return self._jwt_settings.refresh_token_expire_days * 24 * 60 * 60

    def _decode_or_unauthorized(self, token: str, *, expected_type: str) -> dict:
        """Декодировать токен; при ошибке — 401."""
        try:
            return self._security.decode_token(token, expected_type=expected_type)
        except (pyjwt.PyJWTError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
            ) from None

    def _set_token_cookies(self, response: Response, token_pair: TokenPair) -> None:
        """Выдать токены клиенту только через HttpOnly-куки."""
        # Access-кука: короткоживущая, доступна всем путям API
        response.set_cookie(
            key=self._jwt_settings.access_cookie_name,
            value=token_pair.access_token,
            max_age=self._jwt_settings.access_token_expire_minutes * 60,
            path="/",
            domain=self._jwt_settings.cookie_domain,
            secure=self._jwt_settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        # Refresh-кука: долгоживущая, область ограничена путём auth-эндпоинтов
        response.set_cookie(
            key=self._jwt_settings.refresh_cookie_name,
            value=token_pair.refresh_token,
            max_age=self._refresh_ttl_seconds(),
            path="/api/v1/auth",
            domain=self._jwt_settings.cookie_domain,
            secure=self._jwt_settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )

    def _clear_token_cookies(self, response: Response) -> None:
        """Удалить auth-куки у клиента."""
        response.delete_cookie(
            key=self._jwt_settings.access_cookie_name,
            path="/",
            domain=self._jwt_settings.cookie_domain,
        )
        response.delete_cookie(
            key=self._jwt_settings.refresh_cookie_name,
            path="/api/v1/auth",
            domain=self._jwt_settings.cookie_domain,
        )
