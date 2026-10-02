"""Репозиторий системных настроек (singleton-запись)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AppSettings


class AppSettingsRepository:
    """Доступ к единственной записи системных настроек."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> AppSettings | None:
        """Вернуть запись настроек (первую), если она создана."""
        result = await self._session.execute(select(AppSettings).limit(1))
        return result.scalar_one_or_none()

    async def get_or_create(self) -> AppSettings:
        """Вернуть настройки, создав запись со значениями по умолчанию при отсутствии."""
        settings = await self.get()
        if settings is None:
            settings = AppSettings()
            self._session.add(settings)
            await self._session.flush()
        return settings

    async def update(self, values: dict) -> AppSettings:
        """Обновить переданные поля настроек (только непустые ключи)."""
        settings = await self.get_or_create()
        for field, value in values.items():
            setattr(settings, field, value)
        await self._session.flush()
        await self._session.refresh(settings)
        return settings
