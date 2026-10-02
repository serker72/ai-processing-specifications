"""Эндпоинты менеджера: матчинг строк спецификации с каталогом (Модуль 4).

Важно: dishka обрабатывает FromDishka[T] только в параметрах эндпоинта,
поэтому авторизация выполняется вызовом helpers из app.api.deps внутри
обработчика, а не через вложенные Depends.
"""

import asyncio
import io
import json
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_manager
from app.core.config import Settings
from app.core.messages import CommonMessages
from app.models.models import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.client import ClientCreate, ClientListResponse, ClientResponse, ClientUpdate
from app.schemas.confirm_match import ConfirmMatchRequest, ConfirmMatchResponse
from app.schemas.matching import MatchRequest, MatchResponse
from app.schemas.proposal import ProposalGenerateRequest, ProposalItem, ProposalListResponse
from app.schemas.specification import (
    RowMatchesResponse,
    RowStatusUpdateRequest,
    SpecificationRowItem,
    SpecificationRowListResponse,
    SpecificationUploadDetail,
    SpecificationUploadListResponse,
)
from app.services.client_service import (
    ClientNotFoundError,
    ClientService,
    ClientUpdateForbiddenError,
)
from app.services.matching_service import MatchingService
from app.services.proposal_service import (
    NoRowsToExportError,
    ProposalNotFoundError,
    ProposalService,
    ProposalSpecificationNotFoundError,
)
from app.services.security import SecurityService
from app.services.specification_service import FileTooLargeError, SpecificationService
from app.worker.tasks import process_specification

manager_router = APIRouter(route_class=DishkaRoute, prefix="/manager", tags=["manager"])


def parse_upload_id(upload_id: str) -> UUID:
    """UUID загрузки из пути маршрута; неверный формат — 404 (объекта с таким нет)."""
    try:
        return UUID(upload_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND) from None


def parse_row_id(row_id: str) -> UUID:
    """UUID строки из пути маршрута; неверный формат — 404 (объекта с таким нет)."""
    try:
        return UUID(row_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND) from None


def parse_client_id(client_id: str) -> UUID:
    """UUID клиента из пути маршрута; неверный формат — 404 (объекта с таким нет)."""
    try:
        return UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND) from None


def parse_proposal_id(proposal_id: str) -> UUID:
    """UUID КП из пути маршрута; неверный формат — 404 (объекта с таким нет)."""
    try:
        return UUID(proposal_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CommonMessages.NOT_FOUND) from None


def _parse_optional_uuid(raw: str | None) -> UUID | None:
    """Необязательный UUID из тела запроса; неверный формат — ошибка валидации (422)."""
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CommonMessages.VALIDATION_ERROR
        ) from e


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


@manager_router.get(
    "/specifications",
    response_model=SpecificationUploadListResponse,
    status_code=status.HTTP_200_OK,
    summary="Список ранее загруженных спецификаций",
)
async def list_specifications(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
) -> SpecificationUploadListResponse:
    """Загрузки спецификаций текущего менеджера: свежие — первыми."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    try:
        uploads = await specification_service.list_uploads(manager.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return SpecificationUploadListResponse(uploads=uploads)


@manager_router.get(
    "/specifications/{upload_id}",
    response_model=SpecificationUploadDetail,
    status_code=status.HTTP_200_OK,
    summary="Карточка спецификации: статус обработки и сводка по строкам",
)
async def get_specification(
    upload_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
) -> SpecificationUploadDetail:
    """Спецификация текущего менеджера: файл, статус, маппинг, счётчики строк."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    try:
        detail = await specification_service.get_upload(parse_upload_id(upload_id), manager.id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return detail


@manager_router.get(
    "/specifications/{upload_id}/rows",
    response_model=SpecificationRowListResponse,
    status_code=status.HTTP_200_OK,
    summary="Страница строк спецификации с результатами матчинга",
)
async def list_specification_rows(
    upload_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
    page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500, description="Размер страницы")] = 50,
    status_filter: Annotated[
        str | None, Query(alias="status", description="Фильтр по статусу строки (RowStatus)")
    ] = None,
) -> SpecificationRowListResponse:
    """Строки спецификации текущего менеджера: порядковые номера, матчинг, позиции каталога."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    try:
        rows, total = await specification_service.list_rows(
            upload_id=parse_upload_id(upload_id),
            manager_id=manager.id,
            status=status_filter,
            page=page,
            page_size=page_size,
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return SpecificationRowListResponse(rows=rows, total=total, page=page, page_size=page_size)


@manager_router.get(
    "/specifications/{upload_id}/stream",
    summary="SSE-поток обработки спецификации (Real-Time прогресс)",
)
async def stream_specification_progress(
    upload_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
) -> StreamingResponse:
    """SSE-эндпоинт для real-time отслеживания обработки спецификации.

    Клиент подписывается на Redis Pub/Sub канал `spec_{upload_id}` и получает
    события по мере обработки каждой строки Matching Engine.
    """
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    # Подписка только на собственную загрузку: канал чужого upload_id недоступен
    try:
        await specification_service.get_upload(parse_upload_id(upload_id), manager.id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    from app.worker.redis_pubsub import RedisPubSub

    channel = f"spec_{upload_id}"
    redis_pubsub = RedisPubSub()

    async def event_generator():
        """Генератор SSE-событий: воспроизведение буфера Redis, затем live-подписка.

        Подписка выполняется до чтения буфера, а события нумеруются полем `seq`:
        так пересечение буфера и live-ленты не порождает дубликатов, и события,
        опубликованные до подключения клиента, не теряются.
        """
        pubsub = None
        try:
            pubsub = await redis_pubsub.subscribe(channel)

            def take(raw: str) -> bool:
                """Пропустить событие с seq <= последнего отправленного (дедупликация)."""
                nonlocal last_seq
                try:
                    seq = json.loads(raw).get("seq")
                except (ValueError, AttributeError):
                    return True  # не наш JSON — отдаём как есть
                if seq is None:
                    return True
                if seq <= last_seq:
                    return False
                last_seq = int(seq)
                return True

            last_seq = 0
            for raw in await redis_pubsub.buffered_events(channel):
                if take(raw):
                    yield f"data: {raw}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    data = message["data"]
                    if take(data):
                        yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            await redis_pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Отключить буферизацию nginx
        },
    )


@manager_router.post(
    "/specifications",
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить спецификацию клиента: сохранить в MinIO, превью, LLM-маппинг колонок",
)
async def upload_specification(
    file: Annotated[UploadFile, File(...)],
    client_id: Annotated[str, Form(...)],
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
) -> dict:
    """Загрузить Excel-спецификацию: потоковая загрузка в MinIO, превью 50 строк, LLM-маппинг колонок."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CommonMessages.VALIDATION_ERROR)

    try:
        client_uuid = UUID(client_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CommonMessages.VALIDATION_ERROR
        ) from None

    try:
        result = await specification_service.upload_and_predict(
            fileobj=file.file,
            original_filename=file.filename,
            manager_id=manager.id,
            client_id=client_uuid,
        )

        # Запустить фоновую обработку строк через Matching Engine.
        # Commit до .delay(): иначе воркер выберет задачу раньше, чем upload
        # станет виден в базе, и обработает несуществующую загрузку.
        upload_id = result["upload_id"]
        await specification_service.commit_upload()
        process_specification.delay(upload_id, str(manager.id))

    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return result


@manager_router.patch(
    "/specifications/{upload_id}/rows/{row_id}",
    response_model=SpecificationRowItem,
    status_code=status.HTTP_200_OK,
    summary="Изменить статус строки: подтвердить с позицией или исключить",
)
async def update_row_status(
    upload_id: str,
    row_id: str,
    payload: RowStatusUpdateRequest,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
    matching_service: FromDishka[MatchingService],
) -> SpecificationRowItem:
    """Подтвердить строку с выбранной позицией каталога (Tier-1) или исключить."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        result = await specification_service.update_row_status(
            upload_id=parse_upload_id(upload_id),
            manager_id=manager.id,
            row_id=parse_row_id(row_id),
            status=payload.status,
            catalog_item_id=_parse_optional_uuid(payload.catalog_item_id),
            matching_service=matching_service,
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return result


@manager_router.get(
    "/specifications/{upload_id}/rows/{row_id}/matches",
    response_model=RowMatchesResponse,
    status_code=status.HTTP_200_OK,
    summary="Топ-N кандидатов векторного поиска для строки спецификации",
)
async def get_row_matches(
    upload_id: str,
    row_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    specification_service: FromDishka[SpecificationService],
    matching_service: FromDishka[MatchingService],
    limit: Annotated[
        int, Query(ge=1, le=20, description="Число кандидатов (по умолчанию 5)")
    ] = 5,
) -> RowMatchesResponse:
    """Возвращает текущую сопоставленную позицию и топ-N кандидатов векторного поиска."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        result = await specification_service.get_row_matches(
            upload_id=parse_upload_id(upload_id),
            manager_id=manager.id,
            row_id=parse_row_id(row_id),
            limit=limit,
            matching_service=matching_service,
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return result


@manager_router.get(
    "/clients",
    response_model=ClientListResponse,
    status_code=status.HTTP_200_OK,
    summary="Список клиентов (все клиенты доступны менеджерам для выбора)",
)
async def list_clients(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    client_service: FromDishka[ClientService],
    search: Annotated[str | None, Query(description="Подстрока в наименовании или ИНН")] = None,
) -> ClientListResponse:
    """Все клиенты системы; менеджер может выбрать любого при загрузке спецификации."""
    await get_current_manager(request, settings, security_service, session_repository, user_repository)

    try:
        clients = await client_service.list_clients(search=search)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return ClientListResponse(clients=clients)


@manager_router.post(
    "/clients",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать клиента",
)
async def create_client(
    payload: ClientCreate,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    client_service: FromDishka[ClientService],
) -> ClientResponse:
    """Создать нового клиента от имени текущего менеджера."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    try:
        return await client_service.create_client(payload, user_id=manager.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e


@manager_router.patch(
    "/clients/{client_id}",
    response_model=ClientResponse,
    status_code=status.HTTP_200_OK,
    summary="Изменить клиента (менеджер — только созданного им)",
)
async def update_client(
    client_id: str,
    payload: ClientUpdate,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    client_service: FromDishka[ClientService],
) -> ClientResponse:
    """Обновить клиента; менеджер может изменять только созданных им клиентов."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )

    try:
        return await client_service.update_client(
            parse_client_id(client_id), payload, user_id=manager.id, is_admin=False
        )
    except ClientNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ClientUpdateForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e


@manager_router.get(
    "/specifications/{upload_id}/proposal",
    response_model=ProposalItem | None,
    status_code=status.HTTP_200_OK,
    summary="Текущее КП по спецификации (без формирования файла)",
)
async def get_specification_proposal(
    upload_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_service: FromDishka[ProposalService],
) -> ProposalItem | None:
    """Метаданные КП: номер, наличие файла и признак устаревания (null, если КП ещё не формировалось)."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        return await proposal_service.get_state(parse_upload_id(upload_id), manager.id)
    except ProposalSpecificationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e


@manager_router.post(
    "/specifications/{upload_id}/proposal",
    response_model=ProposalItem,
    status_code=status.HTTP_200_OK,
    summary="Сформировать КП по спецификации (или вернуть существующее)",
)
async def generate_specification_proposal(
    upload_id: str,
    payload: ProposalGenerateRequest,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_service: FromDishka[ProposalService],
) -> ProposalItem:
    """Сформировать PDF КП; `force=true` — новая версия файла под тем же номером."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        return await proposal_service.generate(
            parse_upload_id(upload_id), manager.id, force=payload.force
        )
    except ProposalSpecificationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except NoRowsToExportError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e


@manager_router.get(
    "/proposals",
    response_model=ProposalListResponse,
    status_code=status.HTTP_200_OK,
    summary="История сформированных КП менеджера",
)
async def list_proposals(
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_service: FromDishka[ProposalService],
) -> ProposalListResponse:
    """Все КП текущего менеджера (свежие — первыми)."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        proposals = await proposal_service.list_proposals(manager.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return ProposalListResponse(proposals=proposals)


@manager_router.get(
    "/proposals/{proposal_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Скачать PDF КП (формирует файл при первом обращении)",
)
async def download_proposal(
    proposal_id: str,
    request: Request,
    settings: FromDishka[Settings],
    security_service: FromDishka[SecurityService],
    session_repository: FromDishka[SessionRepository],
    user_repository: FromDishka[UserRepository],
    proposal_service: FromDishka[ProposalService],
) -> StreamingResponse:
    """Отдать последнюю версию файла КП; при отсутствии файла — сформировать."""
    manager: User = await get_current_manager(
        request, settings, security_service, session_repository, user_repository
    )
    try:
        content, filename = await proposal_service.download(parse_proposal_id(proposal_id), manager.id)
    except ProposalNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except NoRowsToExportError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=CommonMessages.INTERNAL_ERROR,
        ) from e

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
