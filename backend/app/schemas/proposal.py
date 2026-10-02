"""Pydantic-схемы коммерческих предложений."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProposalDocumentItem(BaseModel):
    """Версия файла КП."""

    id: str
    format: str
    created_at: datetime
    is_current: bool = Field(False, description="Является ли версия последней сформированной")


class ProposalItem(BaseModel):
    """Коммерческое предложение (метаданные)."""

    id: str = Field(..., description="Идентификатор КП")
    number: str = Field(..., description="Номер КП")
    created_at: datetime = Field(..., description="Время создания КП")
    client_id: str = Field(..., description="Идентификатор клиента")
    client_name: str | None = Field(None, description="Наименование клиента")
    upload_id: str = Field(..., description="Идентификатор спецификации-источника")
    filename: str | None = Field(None, description="Имя исходного файла спецификации")
    documents_count: int = Field(0, description="Сколько версий файла сформировано")
    latest_document_id: str | None = Field(None, description="Последняя версия файла")
    has_document: bool = Field(False, description="Сформирован ли файл КП")
    needs_regeneration: bool = Field(
        False, description="Изменились ли строки спецификации после последнего формирования"
    )


class ProposalGenerateRequest(BaseModel):
    """Запрос на формирование КП."""

    force: bool = Field(False, description="Сформировать повторно (новая версия файла)")


class ProposalListResponse(BaseModel):
    """Список коммерческих предложений."""

    proposals: list[ProposalItem]
