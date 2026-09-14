"""Сервис администрирования серверных сессий (панель администратора).

Сессия живёт в Redis по ключу `session:{user_id}:{fingerprint_hash}` и хранит
активный refresh-токен. Отзыв сессии удаляет ключ и добавляет jti этого
refresh-токена в blacklist, поэтому обновить пару токенов нельзя.
Ограничение архитектуры: access-токен не хранится на сервере, он доживает
свой короткий срок (access_token_expire_minutes) и после отзыва не обновляется.

Управление сессиями доступно только администратору: у пользователя нет
эндпоинтов для отзыва собственных сессий — он выходит сам (POST /auth/logout).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from fastapi import HTTPException, status

from app.core.messages import AuthMessages
from app.models.models import UserRole
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.session import SessionItem
from app.services.security import SecurityService


class SessionAdminService:
    """Список активных сессий и их отзыв (в том числе по устройству)."""

    def __init__(
        self,
        session_repository: SessionRepository,
        user_repository: UserRepository,
        security_service: SecurityService,
    ) -> None:
        self._session_repository = session_repository
        self._user_repository = user_repository
        self._security = security_service

    async def list_sessions(self, user_id: str | None = None) -> list[SessionItem]:
        """Активные сессии: id, пользователь с ролью, устройство, время входа и истечения.

        @param user_id — фильтровать сессии одного пользователя (фильтр панели).
        """
        now = datetime.now(UTC)
        known: dict[str, tuple[str, UserRole | None]] = {}
        sessions: list[SessionItem] = []

        for record in await self._session_repository.list_sessions(user_id):
            if record.ttl_seconds <= 0:
                # Ключ без TTL или на пороге удаления — в список не попадает
                continue
            if record.user_id not in known:
                user = await self._user_repository.get_by_id(record.user_id)
                known[record.user_id] = (user.email, user.role) if user else ("", None)
            email, role = known[record.user_id]
            sessions.append(
                SessionItem(
                    id=self.session_id(record.user_id, record.fingerprint_hash),
                    user_id=record.user_id,
                    email=email,
                    role=role,
                    fingerprint_hash=record.fingerprint_hash,
                    started_at=self._session_started_at(record.refresh_token),
                    expires_at=now + timedelta(seconds=record.ttl_seconds),
                )
            )

        return sessions

    async def revoke_session(self, user_id: str, fingerprint_hash: str) -> None:
        """Отозвать сессию: удалить ключ Redis и отправить jti refresh-токена в blacklist."""
        refresh_token = await self._session_repository.get_session(user_id, fingerprint_hash)
        if refresh_token is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.SESSION_NOT_FOUND
            )

        await self._revoke_refresh_token(refresh_token)
        await self._session_repository.delete_session(user_id, fingerprint_hash)

    async def revoke_by_fingerprint(self, fingerprint_hash: str) -> int:
        """Отозвать все сессии устройства; возвращает число отозванных сессий."""
        revoked = 0
        for record in await self._session_repository.list_sessions():
            if record.fingerprint_hash != fingerprint_hash:
                continue
            await self._revoke_refresh_token(record.refresh_token)
            await self._session_repository.delete_session(record.user_id, record.fingerprint_hash)
            revoked += 1
        return revoked

    @staticmethod
    def session_id(user_id: str, fingerprint_hash: str) -> str:
        """Id сессии для панели: составной ключ Redis (user_id + отпечаток устройства)."""
        return f"{user_id}:{fingerprint_hash}"

    def _session_started_at(self, refresh_token: str) -> datetime | None:
        """Время входа сессии по iat refresh-токена (None, если токен не декодируется).

        Refresh-токен ротируется на каждом /auth/refresh, поэтому iat — это время
        последнего обновления пары токенов, а не самого первого входа.
        """
        payload = self._decode_refresh_token(refresh_token)
        issued_at = payload.get("iat") if payload else None
        if not isinstance(issued_at, int):
            return None
        return datetime.fromtimestamp(issued_at, UTC)

    def _decode_refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """Декодировать refresh-токен сессии; None — если подпись или тип не прошли."""
        try:
            return self._security.decode_token(refresh_token, expected_type="refresh")
        except (pyjwt.PyJWTError, ValueError):
            return None

    async def _revoke_refresh_token(self, refresh_token: str) -> None:
        """Добавить jti refresh-токена в blacklist с TTL = остаток его жизни."""
        payload = self._decode_refresh_token(refresh_token)
        if payload is None:
            # Токен не декодируется — отзыв сводится к удалению ключа сессии
            return
        remaining = int(payload.get("exp", 0)) - int(datetime.now(UTC).timestamp())
        await self._session_repository.revoke_jti(str(payload.get("jti")), ttl_seconds=max(remaining, 0))
