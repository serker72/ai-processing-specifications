"""Pydantic-схемы клиентов (покупателей)."""

from datetime import datetime

from pydantic import BaseModel, Field


class ClientCreate(BaseModel):
    """Создание клиента: обязательны наименование, ИНН, адрес, контактное лицо, email."""

    name: str = Field(..., min_length=1, description="Наименование клиента")
    inn: str = Field(..., min_length=1, description="ИНН клиента")
    address: str = Field(..., min_length=1, description="Адрес клиента")
    contact_person: str = Field(..., min_length=1, description="Контактное лицо")
    email: str = Field(..., min_length=1, description="Email клиента")
    phone: str | None = Field(None, description="Телефон клиента")


class ClientUpdate(BaseModel):
    """Частичное обновление клиента: передаются только изменяемые поля."""

    name: str | None = Field(None, min_length=1)
    inn: str | None = Field(None, min_length=1)
    address: str | None = Field(None, min_length=1)
    contact_person: str | None = Field(None, min_length=1)
    email: str | None = Field(None, min_length=1)
    phone: str | None = None


class ClientResponse(BaseModel):
    """Данные клиента."""

    id: str
    name: str
    inn: str
    address: str
    contact_person: str
    email: str
    phone: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_client(cls, client) -> "ClientResponse":
        """ORM-клиент → ответ (UUID-идентификаторы приводятся к строкам)."""
        return cls(
            id=str(client.id),
            name=client.name,
            inn=client.inn,
            address=client.address,
            contact_person=client.contact_person,
            email=client.email,
            phone=client.phone,
            created_by=str(client.created_by),
            created_at=client.created_at,
            updated_at=client.updated_at,
        )


class ClientListResponse(BaseModel):
    """Список клиентов."""

    clients: list[ClientResponse]
