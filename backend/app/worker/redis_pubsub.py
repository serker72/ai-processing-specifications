"""Redis Pub/Sub для публикации прогресса обработки спецификаций.

Pub/Sub не имеет backlog: подписчик, пришедший позже публикации, теряет
события. Поэтому каждое событие дополнительно кладывается в буфер —
Redis LIST `<канал>:events` (LPUSH + LTRIM + TTL), откуда отдаётся
при подписке на SSE до перехода на live-ленту.
"""

import redis.asyncio as redis
from redis.asyncio import ConnectionPool

from app.core.config import get_settings

# Максимальное число событий в буфере на загрузку (старые отсекаются LTRIM)
EVENT_BUFFER_MAX = 2000
# Время жизни буфера событий (после завершения обработки он больше не нужен)
EVENT_BUFFER_TTL_SECONDS = 3600


def event_buffer_key(channel: str) -> str:
    """Ключ Redis LIST с буфером событий канала."""
    return f"{channel}:events"


def seq_counter_key(channel: str) -> str:
    """Ключ-счётчик номеров событий канала."""
    return f"{channel}:seq"


class RedisPubSub:
    """Обёртка над Redis Pub/Sub: публикация с буфером, подписка, воспроизведение буфера."""

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

    async def publish(self, channel: str, message: str, *, buffered: bool = False) -> None:
        """Опубликовать сообщение в канал.

        Args:
            channel: канал Pub/Sub.
            message: тело сообщения (JSON строка).
            buffered: кладать ли событие в буфер LIST для поздних подписчиков SSE.
        """
        client = await self._ensure_client()
        if not buffered:
            await client.publish(channel, message)
            return

        key = event_buffer_key(channel)
        pipe = client.pipeline(transaction=False)
        pipe.publish(channel, message)
        pipe.lpush(key, message)  # свежее — в начало
        pipe.ltrim(key, 0, EVENT_BUFFER_MAX - 1)  # держать только последние
        pipe.expire(key, EVENT_BUFFER_TTL_SECONDS)
        await pipe.execute()

    async def next_seq(self, channel: str) -> int:
        """Следующий номер события канала (Redis INCR).

        Один канал могут писать несколько тасок (``pricelist_{id}``: сначала
        LLM-маппинг, затем векторизация). Локальный счётчик таски начинается
        с единицы и конфликтует с номерами предыдущей таски при переигрывании
        SSE-буфера. Общий INCR-счётчик сохраняет монотонность между тасками;
        TTL сбрасывается на время жизни буфера — после его истечения счётчик
        не нужен.
        """
        client = await self._ensure_client()
        seq = await client.incr(seq_counter_key(channel))
        await client.expire(seq_counter_key(channel), EVENT_BUFFER_TTL_SECONDS)
        return int(seq)

    async def buffered_events(self, channel: str) -> list[str]:
        """События из буфера канала в хронологическом порядке (старые — первыми)."""
        client = await self._ensure_client()
        # LPUSH кладёт свежие в начало, LRANGE отдаёт новые→старые: разворачиваем
        events = await client.lrange(event_buffer_key(channel), 0, -1)
        return list(reversed(events))

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
