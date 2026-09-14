"""Репозиторий серверных сессий и blacklist в Redis.

Ключи:
- session:{user_id}:{fingerprint_hash} — refresh-токен активной сессии (TTL 7 дней);
- revoked:{jti} — отметка отозванного токена (TTL = остаток жизни токена).
"""

from dataclasses import dataclass

from redis.asyncio import Redis

_SESSION_PREFIX = "session"
_REVOKED_PREFIX = "revoked"


@dataclass(frozen=True)
class SessionRecord:
    """Запись активной сессии из Redis: ключ, TTL и refresh-токен."""

    user_id: str
    fingerprint_hash: str
    ttl_seconds: int
    refresh_token: str


class SessionRepository:
    """Доступ к серверным сессиям и blacklist токенов (Redis)."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _session_key(user_id: str, fingerprint_hash: str) -> str:
        return f"{_SESSION_PREFIX}:{user_id}:{fingerprint_hash}"

    @staticmethod
    def _revoked_key(jti: str) -> str:
        return f"{_REVOKED_PREFIX}:{jti}"

    async def save_session(self, user_id: str, fingerprint_hash: str, refresh_token: str, ttl_seconds: int) -> None:
        """Сохранить refresh-токен сессии с TTL."""
        await self._redis.set(
            self._session_key(user_id, fingerprint_hash),
            refresh_token,
            ex=ttl_seconds,
        )

    async def get_session(self, user_id: str, fingerprint_hash: str) -> str | None:
        """Получить refresh-токен активной сессии (None, если сессии нет)."""
        value = await self._redis.get(self._session_key(user_id, fingerprint_hash))
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def delete_session(self, user_id: str, fingerprint_hash: str) -> None:
        """Удалить сессию (логаут)."""
        await self._redis.delete(self._session_key(user_id, fingerprint_hash))

    async def revoke_jti(self, jti: str, ttl_seconds: int) -> None:
        """Добавить jti в blacklist с TTL = остаток жизни токена."""
        if ttl_seconds > 0:
            await self._redis.set(self._revoked_key(jti), "1", ex=ttl_seconds)

    async def is_jti_revoked(self, jti: str) -> bool:
        """Проверить, отозван ли токен (есть ли в blacklist)."""
        return bool(await self._redis.exists(self._revoked_key(jti)))

    async def list_sessions(self, user_id: str | None = None) -> list[SessionRecord]:
        """Перечислить активные сессии (при user_id — только сессии этого пользователя).

        Ключи вида `session:{user_id}:{fingerprint_hash}`; user_id — UUID,
        fingerprint_hash — 64 hex-символов, поэтому правая часть ключа
        однозначно отделяется одним разделителем. Отбор по пользователю
        выполняется самим шаблоном SCAN, а не фильтрацией результата.
        """
        pattern = f"{_SESSION_PREFIX}:{user_id}:*" if user_id else f"{_SESSION_PREFIX}:*"
        sessions: list[SessionRecord] = []

        async for raw_key in self._redis.scan_iter(match=pattern, count=100):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
            _, _, remainder = key.partition(":")
            stored_user_id, _, fingerprint_hash = remainder.rpartition(":")
            if not stored_user_id or not fingerprint_hash:
                continue
            ttl = await self._redis.ttl(key)
            refresh_token = await self._redis.get(key)
            if refresh_token is None:
                # Ключ удалён между SCAN и GET (сессия истекла) — пропускаем
                continue
            sessions.append(
                SessionRecord(
                    user_id=stored_user_id,
                    fingerprint_hash=fingerprint_hash,
                    ttl_seconds=int(ttl),
                    refresh_token=refresh_token.decode("utf-8") if isinstance(refresh_token, bytes) else refresh_token,
                )
            )
        return sessions
