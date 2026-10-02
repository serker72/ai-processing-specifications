"""Сервис системных настроек (реквизиты продавца, НДС)."""

from app.repositories.app_settings_repository import AppSettingsRepository
from app.schemas.app_settings import AppSettingsResponse, AppSettingsUpdate


class AppSettingsService:
    """Чтение и обновление singleton-настроек."""

    def __init__(self, repository: AppSettingsRepository) -> None:
        self._repo = repository

    async def get_settings(self) -> AppSettingsResponse:
        """Текущие настройки (запись создаётся со значениями по умолчанию при отсутствии)."""
        settings = await self._repo.get_or_create()
        return AppSettingsResponse.model_validate(settings)

    async def update_settings(self, payload: AppSettingsUpdate) -> AppSettingsResponse:
        """Обновить переданные поля настроек и вернуть актуальное состояние."""
        values = payload.model_dump(exclude_unset=True)
        settings = await self._repo.update(values)
        return AppSettingsResponse.model_validate(settings)
