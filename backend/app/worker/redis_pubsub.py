"""Redis Pub/Sub для публикации прогресса обработки спецификаций."""

import redis.asyncio as redis
from redis.asyncio import ConnectionPool

from app.core.config import get_settings


class RedisPubSub:
    """Минимальная обёртка над Redis Pub/Sub для публикации и подписки."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._pool: ConnectionPool | None = None
        self._redis: redis.Redis | None = None

    async def _ensure_client(self) -> redis.Redis:
        """Ленивая инициализация Redis-клиента."""
        if self._redis is None:
            self._pool = ConnectionPool.from_url(
                self._settings.redis.url,
                decode_responses=True,
            )
            self._redis = redis.Redis(connection_pool=self._pool)
        return self._redis

    async def publish(self, channel: str, message: str) -> None:
        """Опубликовать сообщение в канал."""
        client = await self._ensure_client()
        await client.publish(channel, message)

    async def subscribe(self, channel: str):
        """Подписаться на канал и вернуть итератор сообщений."""
        client = await self._ensure_client()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def close(self) -> None:
        """Закрыть подключение."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        if self._pool:
            await self._pool.disconnect()
