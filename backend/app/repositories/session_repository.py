"""Репозиторий серверных сессий и blacklist в Redis.

Ключи:
- session:{user_id}:{fingerprint_hash} — refresh-токен активной сессии (TTL 7 дней);
- revoked:{jti} — отметка отозванного токена (TTL = остаток жизни токена).
"""

from redis.asyncio import Redis

_SESSION_PREFIX = "session"
_REVOKED_PREFIX = "revoked"


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
