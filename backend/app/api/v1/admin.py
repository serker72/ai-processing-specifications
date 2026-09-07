"""Эндпоинты администратора: загрузка и анализ прайс-листов (Модуль 3).

Важно: dishka обрабатывает FromDishka[T] только в параметрах эндпоинта,
поэтому авторизация выполняется вызовом helpers из app.api.deps внутри
обработчика, а не через вложенные Depends.

Файл передаётся в сервис как поток (UploadFile.file — SpooledTemporaryFile,
после 1 МБ уходит на диск): не читается в память целиком.
"""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.api.deps import get_current_admin
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.models.models import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.confirm_mapping import ConfirmMappingRequest, ConfirmMappingResponse
from app.services.price_list_service import FileTooLargeError, PriceListService
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
