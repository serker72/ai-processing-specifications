"""Репозиторий клиентов (покупателей)."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Client


class ClientRepository:
    """Доступ к таблице clients."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        name: str,
        inn: str,
        address: str,
        contact_person: str,
        email: str,
        created_by: uuid.UUID,
        phone: str | None = None,
    ) -> Client:
        """Создать клиента."""
        client = Client(
            name=name,
            inn=inn,
            address=address,
            contact_person=contact_person,
            email=email,
            phone=phone,
            created_by=created_by,
        )
        self._session.add(client)
        await self._session.flush()
        await self._session.refresh(client)
        return client

    async def get_by_id(self, client_id: uuid.UUID) -> Client | None:
        """Клиент по ID."""
        return await self._session.get(Client, client_id)

    async def list_all(self, search: str | None = None) -> list[Client]:
        """Все клиенты; поиск — по наименованию и ИНН (подстрока)."""
        statement = select(Client)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(Client.name.ilike(pattern), Client.inn.ilike(pattern))
            )
        statement = statement.order_by(Client.name)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def update(self, client: Client, values: dict) -> Client:
        """Обновить переданные поля клиента."""
        for field, value in values.items():
            setattr(client, field, value)
        await self._session.flush()
        await self._session.refresh(client)
        return client

    async def exists_with_inn(self, inn: str) -> bool:
        """Есть ли клиент с таким ИНН (для подсказки о дубликате)."""
        result = await self._session.execute(
            select(func.count()).select_from(Client).where(Client.inn == inn)
        )
        return int(result.scalar_one()) > 0
