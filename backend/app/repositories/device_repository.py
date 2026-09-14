"""Репозиторий fingerprint-устройств (реестр входов и блокировка)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Device


class DeviceRepository:
    """Доступ к реестру устройств (таблица devices)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch(self, fingerprint_hash: str) -> None:
        """Зарегистрировать вход с устройства или отметить последний вход.

        UPSERT по уникальному индексу fingerprint_hash: при первом входе
        создаётся запись, при повторных обновляется только last_seen_at —
        признак блокировки (blocked) при этом не сбрасывается.
        """
        now = datetime.now(UTC)
        statement = (
            pg_insert(Device)
            .values(fingerprint_hash=fingerprint_hash, blocked=False, first_seen_at=now, last_seen_at=now)
            .on_conflict_do_update(
                index_elements=[Device.fingerprint_hash],
                set_={"last_seen_at": now},
            )
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def get_by_fingerprint_hash(self, fingerprint_hash: str) -> Device | None:
        """Найти устройство по хэшу fingerprint."""
        result = await self._session.execute(
            select(Device).where(Device.fingerprint_hash == fingerprint_hash)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Device]:
        """Список устройств: последние входы — первыми."""
        result = await self._session.execute(select(Device).order_by(Device.last_seen_at.desc()))
        return list(result.scalars().all())

    async def set_blocked(self, device: Device, blocked: bool) -> Device:
        """Заблокировать устройство или снять блокировку."""
        device.blocked = blocked
        await self._session.flush()
        return device
