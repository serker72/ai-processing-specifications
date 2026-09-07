"""Эндпоинты менеджера: матчинг строк спецификации с каталогом (Модуль 4).

Важно: dishka обрабатывает FromDishka[T] только в параметрах эндпоинта,
поэтому авторизация выполняется вызовом helpers из app.api.deps внутри
обработчика, а не через вложенные Depends.
"""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.api.deps import get_current_manager
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.confirm_match import ConfirmMatchRequest, ConfirmMatchResponse
from app.schemas.matching import MatchRequest, MatchResponse
from app.services.matching_service import MatchingService
from app.services.security import SecurityService
from app.services.specification_service import FileTooLargeError, SpecificationService

manager_router = APIRouter(route_class=DishkaRoute, prefix="/manager", tags=["manager"])


@manager_router.post(
    "/match",
    response_model=MatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Сопоставить строку спецификации с каталогом (Matching Engine)",
)
async def match_row(
    payload: MatchRequest,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    matching_service: FromDishka[MatchingService],
) -> MatchResponse:
    """Трёхуровневый матчинг: Tier 1 (HistoricalMatch) → Tier 2 (векторный поиск) → Tier 3 (unmatched)."""
    await get_current_manager(request, settings, security_service, session_repository, user_repository)

    try:
        result = await matching_service.match_row(
            raw_name=payload.raw_name,
            sku=payload.sku,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return MatchResponse(result=result)


@manager_router.post(
    "/match/confirm",
    response_model=ConfirmMatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Подтвердить совпадение и сохранить в HistoricalMatch (Tier-1 словарь)",
)
async def confirm_match(
    payload: ConfirmMatchRequest,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    matching_service: FromDishka[MatchingService],
) -> ConfirmMatchResponse:
    """Сохранить подтверждённое совпадение в словарь HistoricalMatch для мгновенного Tier-1 поиска."""
    await get_current_manager(request, settings, security_service, session_repository, user_repository)

    try:
        result = await matching_service.confirm_match(
            raw_name=payload.raw_name,
            catalog_item_id=payload.catalog_item_id,
            tier=payload.tier,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return ConfirmMatchResponse(**result)


@manager_router.post(
    "/specifications",
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить спецификацию клиента: сохранить в MinIO, превью, LLM-маппинг колонок",
)
async def upload_specification(
    file: Annotated[UploadFile, File(...)],
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
) -> dict:
    """Загрузить Excel-спецификацию: потоковая загрузка в MinIO, превью 50 строк, LLM-маппинг колонок."""
    from app.models.models import User

    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CommonMessages.VALIDATION_ERROR)

    try:
        result = await specification_service.upload_and_predict(
            fileobj=file.file,
            original_filename=file.filename,
            manager_id=manager.id,
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
