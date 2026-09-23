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
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from app.api.deps import get_current_admin
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.models.models import UploadStatus, User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.catalog import CatalogItemResponse, CatalogListResponse
from app.schemas.confirm_mapping import ConfirmMappingRequest, ConfirmMappingResponse
from app.schemas.price_list import PriceListListResponse, PriceListPreviewResponse
from app.schemas.proposal_template import (
    ProposalTemplateListResponse,
    ProposalTemplateResponse,
    ProposalTemplateUpdate,
)
from app.services.catalog_service import CatalogService
from app.services.price_list_service import FileTooLargeError, PriceListService
from app.services.proposal_template_service import ProposalTemplateService
from app.services.security import SecurityService
from app.worker.tasks import vectorize_catalog

admin_router = APIRouter(route_class=DishkaRoute, prefix="/admin", tags=["admin"])


@admin_router.get(
    "/pricelists",
    response_model=PriceListListResponse,
    status_code=status.HTTP_200_OK,
    summary="История загрузок прайс-листов",
)
async def list_pricelists(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    price_list_service: FromDishka[PriceListService],
    status_filter: Annotated[
        UploadStatus | None, Query(alias="status", description="Фильтр по статусу обработки")
    ] = None,
) -> PriceListListResponse:
    """Загрузки прайс-листов со статусами обработки (свежие — первыми) и счётчиками статусов."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    uploads, counts = await price_list_service.list_uploads(status_filter)
    return PriceListListResponse(uploads=uploads, counts=counts)


@admin_router.get(
    "/pricelists/{upload_id}/preview",
    response_model=PriceListPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Превью прайс-листа и сохранённый маппинг колонок",
)
async def preview_pricelist(
    upload_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    price_list_service: FromDishka[PriceListService],
) -> PriceListPreviewResponse:
    """Файл из MinIO (первые 50 строк) и сохранённый column_mapping для подтверждения маппинга."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    try:
        result = await price_list_service.get_preview(upload_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CommonMessages.VALIDATION_ERROR) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return PriceListPreviewResponse(**result)


@admin_router.get(
    "/catalog",
    response_model=CatalogListResponse,
    status_code=status.HTTP_200_OK,
    summary="Каталог номенклатуры (страницами, с поиском)",
)
async def list_catalog(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    catalog_service: FromDishka[CatalogService],
    page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    page_size: Annotated[int, Query(ge=1, le=200, description="Размер страницы")] = 50,
    search: Annotated[str | None, Query(description="Подстрока в наименовании или артикуле")] = None,
) -> CatalogListResponse:
    """Позиции каталога, загруженные из прайс-листов."""
    await get_current_admin(request, settings, security_service, session_repository, user_repository)

    items, total = await catalog_service.list_items(search=search, page=page, page_size=page_size)
    return CatalogListResponse(
        items=[CatalogItemResponse.from_item(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


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
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    # Векторизация каталога — только после подтверждения маппинга (иначе прайс
    # так и останется предсказанным, а catalog_items — пустым).
    # Commit до .delay(): воркер не должен увидеть задачу раньше, чем
    # подтверждённый маппинг станет виден в базе.
    await price_list_service.commit_upload()
    vectorize_catalog.delay(upload_id)

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
