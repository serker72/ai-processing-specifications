"""Сервис реестра fingerprint-устройств (панель администратора)."""

from fastapi import HTTPException, status

from app.core.messages import CommonMessages
from app.models.models import Device
from app.repositories.device_repository import DeviceRepository
from app.services.session_admin_service import SessionAdminService


class DeviceService:
    """Список устройств и блокировка входа с устройства."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        session_admin_service: SessionAdminService,
    ) -> None:
        self._device_repository = device_repository
        self._session_admin = session_admin_service

    async def list_devices(self) -> list[Device]:
        """Зарегистрированные устройства (последние входы — первыми)."""
        return await self._device_repository.list_all()

    async def set_blocked(self, fingerprint_hash: str, blocked: bool) -> Device:
        """Заблокировать устройство или снять блокировку.

        При блокировке дополнительно отзываются активные сессии этого
        отпечатка: отзыв refresh-токена закрывает вход, а запрет на вход
        (blocked) не даст сесть заново с того же устройства.
        """
        device = await self._device_repository.get_by_fingerprint_hash(fingerprint_hash)
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND)

        device = await self._device_repository.set_blocked(device, blocked)
        if blocked:
            await self._session_admin.revoke_by_fingerprint(fingerprint_hash)
        return device
