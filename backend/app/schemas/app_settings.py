"""Pydantic-схемы системных настроек (реквизиты продавца, НДС)."""

from pydantic import BaseModel, Field


class AppSettingsResponse(BaseModel):
    """Системные настройки: реквизиты продавца и параметры НДС."""

    seller_name: str | None = Field(None, description="Наименование продавца")
    seller_inn: str | None = Field(None, description="ИНН продавца")
    seller_kpp: str | None = Field(None, description="КПП продавца")
    seller_address: str | None = Field(None, description="Юридический адрес продавца")
    seller_phone: str | None = Field(None, description="Телефон продавца")
    seller_email: str | None = Field(None, description="Email продавца")
    bank_account: str | None = Field(None, description="Расчётный счёт")
    bank_name: str | None = Field(None, description="Наименование банка")
    bank_bik: str | None = Field(None, description="БИК банка")
    corr_account: str | None = Field(None, description="Корреспондентский счёт")
    signer_name: str | None = Field(None, description="ФИО подписанта")
    signer_position: str | None = Field(None, description="Должность подписанта")
    vat_rate: float = Field(..., description="Ставка НДС, %")
    vat_included: bool = Field(..., description="НДС выделен из цены (иначе начисляется сверху)")

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    """Частичное обновление системных настроек: передаются только изменяемые поля."""

    seller_name: str | None = None
    seller_inn: str | None = None
    seller_kpp: str | None = None
    seller_address: str | None = None
    seller_phone: str | None = None
    seller_email: str | None = None
    bank_account: str | None = None
    bank_name: str | None = None
    bank_bik: str | None = None
    corr_account: str | None = None
    signer_name: str | None = None
    signer_position: str | None = None
    vat_rate: float | None = Field(None, ge=0, le=100, description="Ставка НДС, %")
    vat_included: bool | None = None
