"""Pydantic-схемы для шаблонов коммерческих предложений."""

from datetime import date, datetime

from pydantic import BaseModel


class ProposalTemplateCreate(BaseModel):
    """Схема для создания шаблона КП."""

    name: str
    start_date: date


class ProposalTemplateUpdate(BaseModel):
    """Схема для обновления шаблона КП."""

    name: str | None = None
    start_date: date | None = None


class ProposalTemplateResponse(BaseModel):
    """Схема ответа с данными шаблона КП."""

    id: str
    name: str
    html_key: str
    start_date: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProposalTemplateListResponse(BaseModel):
    """Схема ответа со списком шаблонов КП."""

    templates: list[ProposalTemplateResponse]
