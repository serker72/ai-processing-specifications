"""Сервис клиентов (покупателей)."""

import uuid

from app.core.messages import ClientMessages
from app.repositories.client_repository import ClientRepository
from app.schemas.client import ClientCreate, ClientResponse, ClientUpdate


class ClientNotFoundError(LookupError):
    """Клиент не найден."""


class ClientUpdateForbiddenError(PermissionError):
    """Попытка изменить чужого клиента без прав администратора."""


class ClientService:
    """Бизнес-логика клиентов: список, создание, обновление с проверкой прав."""

    def __init__(self, repository: ClientRepository) -> None:
        self._repo = repository

    async def list_clients(self, search: str | None = None) -> list[ClientResponse]:
        """Список клиентов (видны все); поиск по наименованию и ИНН."""
        clients = await self._repo.list_all(search=search)
        return [ClientResponse.from_client(client) for client in clients]

    async def create_client(self, payload: ClientCreate, user_id: uuid.UUID) -> ClientResponse:
        """Создать клиента от имени текущего пользователя."""
        client = await self._repo.create(
            name=payload.name,
            inn=payload.inn,
            address=payload.address,
            contact_person=payload.contact_person,
            email=payload.email,
            phone=payload.phone,
            created_by=user_id,
        )
        return ClientResponse.from_client(client)

    async def update_client(
        self,
        client_id: uuid.UUID,
        payload: ClientUpdate,
        user_id: uuid.UUID,
        is_admin: bool,
    ) -> ClientResponse:
        """Обновить клиента.

        Менеджер может изменять только созданных им клиентов; администратор — любых.

        Raises:
            ClientNotFoundError: клиент не найден.
            ClientUpdateForbiddenError: менеджер пытается изменить чужого клиента.
        """
        client = await self._repo.get_by_id(client_id)
        if client is None:
            raise ClientNotFoundError(ClientMessages.NOT_FOUND)
        if not is_admin and client.created_by != user_id:
            raise ClientUpdateForbiddenError(ClientMessages.UPDATE_FORBIDDEN)

        values = payload.model_dump(exclude_unset=True)
        client = await self._repo.update(client, values)
        return ClientResponse.from_client(client)
