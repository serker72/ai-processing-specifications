"""Эндпоинты администратора: загрузка и анализ прайс-листов (Модуль 3).

Важно: dishka обрабатывает FromDishka[T] только в параметрах эндпоинта,
поэтому авторизация выполняется вызовом helpers из app.api.deps внутри
обработчика, а не через вложенные Depends.

Файл передаётся в сервис как поток (UploadFile.file — SpooledTemporaryFile,
после 1 МБ уходит на диск): не читается в память целиком.
"""

from datetime import date
from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.api.deps import get_current_admin
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.models.models import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.confirm_mapping import ConfirmMappingRequest, ConfirmMappingResponse
from app.schemas.proposal_template import (
    ProposalTemplateListResponse,
    ProposalTemplateResponse,
    ProposalTemplateUpdate,
)
from app.services.price_list_service import FileTooLargeError, PriceListService
from app.services.proposal_template_service import ProposalTemplateService
from app.services.security import SecurityService

admin_router = APIRouter(route_class=DishkaRoute, prefix="/admin", tags=["admin"])


@admin_router.post(
    "/pricelists",
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить прайс-лист: сохранить в MinIO, превью, LLM-маппинг колонок",
)
async def upload_pricelist(
    file: Annotated[UploadFile, File(...)],
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    price_list_service: FromDishka[PriceListService],
) -> dict:
    """Загрузить Excel-прайс-лист: потоковая загрузка в MinIO, превью 50 строк, LLM-маппинг колонок."""
    admin: User = await get_current_admin(request, settings, security_service, session_repository, user_repository)

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CommonMessages.VALIDATION_ERROR)

    try:
        result = await price_list_service.upload_and_predict(
            fileobj=file.file,
            original_filename=file.filename,
            admin_id=admin.id,
        )
    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return result


@admin_router.post(
    "/pricelists/{upload_id}/confirm",
    response_model=ConfirmMappingResponse,
    status_code=status.HTTP_200_OK,
    summary="Подтвердить или отредактировать маппинг колонок прайс-листа",
)
async def confirm_pricelist_mapping(
    upload_id: str,
    payload: ConfirmMappingRequest,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    price_list_service: FromDishka[PriceListService],
) -> ConfirmMappingResponse:
    """Подтвердить или отредактировать маппинг, запустить фоновую векторизацию каталога."""
    admin: User = await get_current_admin(request, settings, security_service, session_repository, user_repository)

    try:
        result = await price_list_service.confirm_mapping(
            upload_id=upload_id,
            payload=payload,
            admin_id=admin.id,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return result


@admin_router.post(
    "/proposal-templates",
    response_model=ProposalTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить шаблон КП: HTML-файл в MinIO, валидация даты",
)
async def upload_proposal_template(
    file: Annotated[UploadFile, File(...)],
    name: Annotated[str, Form(...)],
    start_date: Annotated[date, Form(...)],
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_template_service: FromDishka[ProposalTemplateService],
) -> ProposalTemplateResponse:
    """Загрузить HTML-шаблон КП: валидация даты, загрузка в MinIO, сохранение в БД."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    if not file.filename or not file.filename.endswith(".html"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл должен быть HTML-шаблоном (.html)")

    try:
        template = await proposal_template_service.create_template(
            name=name,
            html_file=file.file,
            start_date=start_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return ProposalTemplateResponse.model_validate(template)


@admin_router.get(
    "/proposal-templates",
    response_model=ProposalTemplateListResponse,
    status_code=status.HTTP_200_OK,
    summary="Список всех шаблонов КП",
)
async def list_proposal_templates(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_template_service: FromDishka[ProposalTemplateService],
) -> ProposalTemplateListResponse:
    """Возвращает список всех шаблонов КП, отсортированный по дате начала (DESC)."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    templates = await proposal_template_service.list_templates()
    return ProposalTemplateListResponse(
        templates=[ProposalTemplateResponse.model_validate(t) for t in templates]
    )


@admin_router.patch(
    "/proposal-templates/{template_id}",
    response_model=ProposalTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Обновить шаблон КП",
)
async def update_proposal_template(
    template_id: str,
    payload: ProposalTemplateUpdate,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_template_service: FromDishka[ProposalTemplateService],
) -> ProposalTemplateResponse:
    """Обновить название или дату начала шаблона КП."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    import uuid

    try:
        template = await proposal_template_service.update_template(
            template_id=uuid.UUID(template_id),
            name=payload.name,
            start_date=payload.start_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return ProposalTemplateResponse.model_validate(template)


@admin_router.delete(
    "/proposal-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить шаблон КП",
)
async def delete_proposal_template(
    template_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_template_service: FromDishka[ProposalTemplateService],
) -> None:
    """Удалить шаблон КП и файл из MinIO."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    import uuid

    try:
        await proposal_template_service.delete_template(template_id=uuid.UUID(template_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e
