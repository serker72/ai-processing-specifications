"""Celery-таски для фоновой векторизации каталога и обработки спецификаций (Модули 3 и 5).

Обе таски работают в собственном event loop (`asyncio.new_event_loop`) и в
собственной сессии БД: коммит выполняется по батчам, чтобы прогресс был виден
подписчикам SSE и списку загрузок ещё до окончания обработки файла.
Статусы загрузки берутся только из `UploadStatus` — `RowStatus` описывает
строку и к статусу файла отношения не имеет.

Задача 3.1: таска `pricelist.predict_mapping` отвечает за предсказание маппинга
колонок прайс-листа (LLM) — вынесена из HTTP-запроса.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.logging_config import upload_id_var
from app.schemas.sse_events import (
    PriceListStatusEvent,
    ProgressEvent,
    RowMatchEvent,
    SpecificationStatusEvent,
)
from app.worker import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 500  # Строк прайс-листа в одном батче векторизации
BATCH_SIZE_SPEC = 100  # Строк спецификации в одном батче матчинга

# Получаем экземпляр celery_app для регистрации таски
_celery_app = celery_app


def _run_async(coro_factory: Any) -> Any:
    """Выполнить корутину в новом event loop (Celery-таска синхронная)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        # Закрыть aioboto3-клиенты (MinioService — Singleton), пока loop ещё жив:
        # после loop.close() aiohttp пишет «Unclosed client session/connector».
        from app.services.minio_service import MinioService

        try:
            loop.run_until_complete(MinioService.close_all())
        except Exception:
            logger.warning("Не удалось закрыть MinIO-клиент после таски", exc_info=True)

        # Остановить GLOBAL_LOGGING_WORKER litellm, пока loop ещё жив: его
        # _worker_task привязан к этому loop; после loop.close() задача
        # уничтожается висящей — «Task was destroyed but it is pending» /
        # «RuntimeError: Event loop is closed» в логах worker перед LLM-вызовом.
        # stop() отменяет и дожидается всех задач; сброс _queue/_sem/_bound_loop
        # гарантирует, что следующая таска инициализирует воркер в своём loop
        # (_ensure_queue проверяет смену loop, но не обрабатывает закрытый).
        from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

        try:
            loop.run_until_complete(GLOBAL_LOGGING_WORKER.stop())
            GLOBAL_LOGGING_WORKER._queue = None
            GLOBAL_LOGGING_WORKER._sem = None
            GLOBAL_LOGGING_WORKER._bound_loop = None
        except Exception:
            logger.warning("Не удалось остановить GLOBAL_LOGGING_WORKER", exc_info=True)

        loop.close()


def _json_value(value: Any) -> Any:
    """Значение ячейки Excel → JSON-совместимый тип для raw_data (JSONB).

    Даты и Decimal сериализуются в строку, числа и строки остаются как есть:
    иначе psycopg отклонит весь объект JSONB при вставке строки спецификации.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


@_celery_app.task(bind=True, name="pricelist.predict_mapping")
def predict_pricelist_mapping(self: Any, upload_id: str) -> dict:
    """Предсказание маппинга колонок прайс-листа через LLM (задача 3.1).

    Вынесено из HTTP-запроса загрузки: POST /admin/pricelists сразу возвращает
    202, анализ выполняет эта таска. Переходы статусов
    pending → mapping_processing → mapping_predicted | failed — в сервисе;
    здесь — публикация событий в SSE-канал pricelist_{upload_id} и терминальное
    событие (completed / error) последним.
    """

    async def _run() -> dict:
        from app.core.messages import PriceListMessages
        from app.di.container import create_container
        from app.services.price_list_service import PriceListService
        from app.worker.redis_pubsub import RedisPubSub

        logger.info("Предсказание маппинга прайс-листа: старт")
        container = create_container()
        redis_pubsub = RedisPubSub()
        channel = f"pricelist_{upload_id}"

        # Номер события: общий счётчик канала (Redis INCR) — в тот же канал позже
        # пишет векторизация, нумерация не должна конфликтовать при переигрывании буфера
        async def next_seq() -> int:
            return await redis_pubsub.next_seq(channel)

        async def publish(status: str, message: str) -> None:
            """Опубликовать событие статуса прайс-листа (с кладкой в буфер для поздних подписчиков)."""
            await redis_pubsub.publish(
                channel,
                PriceListStatusEvent(
                    upload_id=upload_id,
                    seq=await next_seq(),
                    status=status,
                    message=message,
                ).model_dump_json(),
                buffered=True,
            )

        try:
            async with container() as c:
                price_list_svc = await c.get(PriceListService)
                await publish("mapping_processing", PriceListMessages.MAPPING_PROCESSING)
                result = await price_list_svc.predict_mapping(upload_id)
                await publish("mapping_predicted", PriceListMessages.MAPPING_READY)
                logger.info("Предсказание маппинга прайс-листа: завершено")
                return result
        except Exception:
            await publish("error", PriceListMessages.MAPPING_FAILED)
            logger.exception("Предсказание маппинга прайс-листа: ошибка, статус failed")
            raise
        finally:
            await redis_pubsub.close()

    token = upload_id_var.set(upload_id)
    try:
        return _run_async(_run)
    finally:
        upload_id_var.reset(token)


@_celery_app.task(bind=True, name="catalog.vectorize")
def vectorize_catalog(self: Any, upload_id: str) -> dict:
    """Фоновая векторизация каталога из подтверждённого прайс-листа.

    Батчами по BATCH_SIZE строк: читает файл из MinIO по column_mapping,
    генерирует эмбеддинги, выполняет UPSERT в CatalogItem по паре (sku, name).
    Статус загрузки: processing → completed | failed.
    """

    async def _mark_failed() -> None:
        """Пометить загрузку ошибкой отдельной сессией (основная уже свёрнута)."""
        from app.db.session import async_session_factory
        from app.models.models import UploadStatus
        from app.repositories.price_list_repository import PriceListRepository

        async with async_session_factory() as session:
            repo = PriceListRepository(session)
            upload = await repo.get_by_id(UUID(upload_id))
            if upload is not None:
                await repo.update_status(upload.id, UploadStatus.failed)
                await session.commit()

    async def _run() -> dict:
        from app.core.messages import PriceListMessages
        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.models.models import UploadStatus
        from app.repositories.catalog_repository import CatalogRepository, content_hash_of
        from app.repositories.price_list_repository import PriceListRepository
        from app.schemas.sse_events import PriceListProgressEvent
        from app.services.embedding_service import EmbeddingService
        from app.services.price_list_service import PriceListService
        from app.worker.redis_pubsub import RedisPubSub

        logger.info("Векторизация каталога: старт")
        container = create_container()
        redis_pubsub = RedisPubSub()
        channel = f"pricelist_{upload_id}"

        async def publish_progress(
            processed: int | None,
            total: int | None,
            status: str,
            message: str,
        ) -> None:
            """Опубликовать прогресс векторизации в канал прайс-листа (с кладкой в буфер).

            processed/total=None — этап подготовки: общее число записей неизвестно
            до чтения файла. Терминальные события — completed / error, по ним клиент
            закрывает поток и обновляет данные; публикуется последним.
            """
            await redis_pubsub.publish(
                channel,
                PriceListProgressEvent(
                    upload_id=upload_id,
                    seq=await redis_pubsub.next_seq(channel),
                    processed=processed,
                    total=total,
                    status=status,
                    message=message,
                ).model_dump_json(),
                buffered=True,
            )

        try:
            async with container() as c:
                embedding_svc = await c.get(EmbeddingService)
                price_list_svc = await c.get(PriceListService)

                async with async_session_factory() as session:
                    price_list_repo = PriceListRepository(session)
                    catalog_repo = CatalogRepository(session)

                    upload = await price_list_repo.get_by_id(UUID(upload_id))
                    if upload is None:
                        logger.warning("Векторизация каталога: загрузка не найдена")
                        await publish_progress(
                            None, None, "error", PriceListMessages.UPLOAD_NOT_FOUND
                        )
                        return {"error": "upload not found", "upload_id": upload_id}
                    if not upload.column_mapping:
                        logger.warning("Векторизация каталога: маппинг колонок не подтверждён")
                        await publish_progress(None, None, "error", PriceListMessages.NO_MAPPING)
                        return {"error": "no column_mapping", "upload_id": upload_id}

                    file_key = upload.file_key
                    column_mapping = upload.column_mapping
                    await price_list_repo.update_status(upload.id, UploadStatus.processing)
                    await session.commit()
                    # Подготовка: total неизвестен до прочтения файла — событие без чисел
                    await publish_progress(
                        None, None, "processing", PriceListMessages.VECTORIZING_PREPARING
                    )

                    total = 0
                    try:
                        rows = await price_list_svc.parse_pricelist(file_key, column_mapping)
                        total = len(rows)
                        logger.info("Векторизация каталога: прочитано строк — %d", total)
                        await publish_progress(0, total, "processing", PriceListMessages.VECTORIZING_STARTED)

                        # Проблема 3: позиции с неизменным content_hash не
                        # отправляются в эмбеддинг-модель — пересчёт только для
                        # новых/изменённых строк (повторная векторизация большого
                        # прайса больше не пересчитывает все эмбеддинги заново)
                        recomputed_total = 0

                        for i in range(0, total, BATCH_SIZE):
                            batch = rows[i : i + BATCH_SIZE]
                            batch_hashes = {
                                (r["sku"], r["name"]): content_hash_of(r["sku"], r["name"])
                                for r in batch
                            }
                            existing_hashes = await catalog_repo.find_hashes_by_keys(
                                list(batch_hashes)
                            )
                            to_embed = [
                                r
                                for r in batch
                                if existing_hashes.get((r["sku"], r["name"]))
                                != batch_hashes[(r["sku"], r["name"])]
                            ]
                            embeddings = embedding_svc.embed_passages(
                                [r["description"] for r in to_embed]
                            )
                            embedding_by_key = {
                                (r["sku"], r["name"]): list(emb)
                                for r, emb in zip(to_embed, embeddings, strict=True)
                            }
                            items = [
                                {
                                    "sku": r["sku"],
                                    "name": r["name"],
                                    "unit": r.get("unit"),
                                    "price": r.get("price"),
                                    "content_hash": batch_hashes[(r["sku"], r["name"])],
                                    # None для unchanged: UPSERT сохранит старый
                                    # эмбеддинг через COALESCE(excluded, stored)
                                    "embedding": embedding_by_key.get((r["sku"], r["name"])),
                                }
                                for r in batch
                            ]
                            # UPSERT: повторная загрузка прайса обновляет позиции,
                            # а не падает на уникальном индексе (sku, name)
                            await catalog_repo.upsert_batch(items)
                            await session.commit()
                            recomputed_total += len(to_embed)
                            processed = min(i + BATCH_SIZE, total)
                            skipped = len(batch) - len(to_embed)
                            # Прогресс после каждого батча: счётчик «N / M записей»
                            # виден в UI до окончания обработки всего файла
                            await publish_progress(
                                processed,
                                total,
                                "processing",
                                PriceListMessages.vectorized_progress(processed, total),
                            )
                            logger.info(
                                "Векторизация каталога: обработано %d/%d строк "
                                "(пересчитано эмбеддингов %d, пропущено %d)",
                                processed,
                                total,
                                len(to_embed),
                                skipped,
                            )

                        await price_list_repo.update_status(upload.id, UploadStatus.completed)
                        await session.commit()
                        # Терминальное событие — последним: клиент по нему закрывает
                        # поток и обновляет данные, не выводя завершение из статусов
                        await publish_progress(total, total, "completed", PriceListMessages.VECTORIZED_DONE)
                        logger.info(
                            "Векторизация каталога: завершена, %d строк, "
                            "эмбеддинги пересчитаны для %d",
                            total,
                            recomputed_total,
                        )
                    except Exception:
                        await session.rollback()
                        await _mark_failed()
                        await publish_progress(None, None, "error", PriceListMessages.VECTORIZING_FAILED)
                        logger.exception("Векторизация каталога: ошибка, статус failed")
                        raise

                    return {"upload_id": upload_id, "total_rows": total, "status": "completed"}
        finally:
            await redis_pubsub.close()

    token = upload_id_var.set(upload_id)
    try:
        return _run_async(_run)
    finally:
        upload_id_var.reset(token)


@_celery_app.task(bind=True, name="catalog.reembed")
def reembed_catalog_item(self: Any, item_id: str, name: str) -> dict:
    """Пересчитать эмбеддинг позиции каталога после правки наименования админом.

    Наименование передаётся аргументом: таска не зависит от момента коммита
    правки в БД и всегда считает вектор по новому значению.
    """

    async def _run() -> dict:
        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.repositories.catalog_repository import CatalogRepository, content_hash_of
        from app.services.embedding_service import EmbeddingService

        logger.info("Пересчёт эмбеддинга позиции каталога: старт (item_id=%s)", item_id)
        container = create_container()
        async with container() as c:
            embedding_svc = await c.get(EmbeddingService)
            embedding = embedding_svc.embed_passages([name])[0]

            async with async_session_factory() as session:
                catalog_repo = CatalogRepository(session)
                item = await catalog_repo.get_by_id(UUID(item_id))
                if item is None:
                    logger.warning("Пересчёт эмбеддинга: позиция не найдена (item_id=%s)", item_id)
                    return {"error": "item not found", "item_id": item_id}
                # Обновляем хэш вместе с эмбеддингом: иначе следующая
                # векторизация посчитает строку unchanged и не пересчитает вектор
                await catalog_repo.update(item, {
                    "embedding": list(embedding),
                    "content_hash": content_hash_of(item.sku, name),
                })
                await session.commit()

        logger.info("Пересчёт эмбеддинга завершён (item_id=%s)", item_id)
        return {"item_id": item_id, "status": "reembedded"}

    return _run_async(_run)


@_celery_app.task(bind=True, name="specification.predict_mapping")
def predict_specification_mapping(self: Any, upload_id: str) -> dict:
    """Предсказание маппинга колонок спецификации через LLM (Задача 5.1).

    Вынесено из HTTP-запроса загрузки: POST /manager/specifications сразу
    возвращает 202, анализ выполняет эта таска. Переходы статусов
    pending → mapping_processing → mapping_predicted | failed — в сервисе;
    здесь — публикация событий в SSE-канал spec_{upload_id} (тот же канал,
    что у матчинга) и запуск process_specification после успеха.
    """

    async def _run() -> dict:
        from app.core.messages import SpecificationMessages
        from app.di.container import create_container
        from app.services.specification_service import SpecificationService
        from app.worker.redis_pubsub import RedisPubSub

        logger.info("Предсказание маппинга спецификации: старт")
        container = create_container()
        redis_pubsub = RedisPubSub()
        channel = f"spec_{upload_id}"

        async def publish(status: str, message: str) -> None:
            """Опубликовать событие статуса маппинга (с кладкой в буфер для поздних подписчиков)."""
            await redis_pubsub.publish(
                channel,
                SpecificationStatusEvent(
                    upload_id=upload_id,
                    # Общий счётчик канала (Redis INCR): в тот же канал пишет
                    # таска матчинга, нумерация не должна конфликтовать
                    seq=await redis_pubsub.next_seq(channel),
                    status=status,
                    message=message,
                ).model_dump_json(),
                buffered=True,
            )

        try:
            async with container() as c:
                spec_svc = await c.get(SpecificationService)
                await publish("mapping_processing", SpecificationMessages.MAPPING_PROCESSING)
                result = await spec_svc.predict_mapping(upload_id)
                await publish("mapping_predicted", SpecificationMessages.MAPPING_READY)
                logger.info("Предсказание маппинга спецификации: завершено, матчинг запущен")
                return result
        except Exception:
            await publish("error", SpecificationMessages.MAPPING_FAILED)
            logger.exception("Предсказание маппинга спецификации: ошибка, статус failed")
            raise
        finally:
            await redis_pubsub.close()

    token = upload_id_var.set(upload_id)
    try:
        return _run_async(_run)
    finally:
        upload_id_var.reset(token)


@_celery_app.task(bind=True, name="specification.process")
def process_specification(
    self: Any,
    upload_id: str,
    manager_id: str,
) -> dict:
    """Фоновая обработка строк спецификации через Matching Engine.

    Алгоритм: читает Excel из MinIO по column_mapping, прогоняет строки через
    MatchingService батчами по BATCH_SIZE_SPEC, пишет SpecificationRow,
    публикует прогресс в Redis Pub/Sub (канал spec_{upload_id}).
    Статус загрузки: processing → completed | failed.
    """

    async def _run() -> dict:
        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.models.models import MatchType, RowStatus, UploadStatus
        from app.repositories.matching_repository import MatchingRepository
        from app.repositories.specification_repository import SpecificationRepository
        from app.services.embedding_service import EmbeddingService
        from app.services.matching_service import MatchingService
        from app.services.minio_service import MinioService
        from app.worker.redis_pubsub import RedisPubSub

        container = create_container()
        redis_pubsub = RedisPubSub()
        channel = f"spec_{upload_id}"

        logger.info("Обработка спецификации: старт (manager_id=%s)", manager_id)

        # Номер события: общий счётчик канала (Redis INCR) — в тот же канал пишет
        # таска предсказания маппинга, нумерация не должна конфликтовать при
        # переигрывании SSE-буфера; по seq подписчик отсекает дубликаты.
        async def next_seq() -> int:
            return await redis_pubsub.next_seq(channel)

        async def publish_progress(processed: int, total: int, status: str, message: str) -> None:
            """Опубликовать событие прогресса в канал загрузки (с кладкой в буфер)."""
            await redis_pubsub.publish(
                channel,
                ProgressEvent(
                    upload_id=upload_id,
                    seq=await next_seq(),
                    processed=processed,
                    total=total,
                    status=status,
                    message=message,
                ).model_dump_json(),
                buffered=True,
            )

        try:
            async with container() as c:
                embedding_svc = await c.get(EmbeddingService)
                minio_svc = await c.get(MinioService)

                async with async_session_factory() as session:
                    spec_repo = SpecificationRepository(session)
                    matching_svc = MatchingService(MatchingRepository(session), embedding_svc)

                    upload = await spec_repo.get_by_id(UUID(upload_id))
                    if upload is None:
                        logger.warning("Обработка спецификации: загрузка не найдена")
                        await publish_progress(0, 0, "error", "Загрузка не найдена")
                        return {"error": "upload not found", "upload_id": upload_id}
                    if not upload.column_mapping:
                        logger.warning("Обработка спецификации: маппинг колонок не подтверждён")
                        await publish_progress(0, 0, "error", "Маппинг колонок не подтверждён")
                        return {"error": "no column_mapping", "upload_id": upload_id}

                    file_key = upload.file_key
                    column_mapping = upload.column_mapping
                    await spec_repo.update_status(upload.id, UploadStatus.processing)
                    await session.commit()

                    # Лист: первая непустая строка — заголовки, дальше — данные
                    wb = await minio_svc.download_workbook(file_key)
                    ws = wb.active
                    sheet_rows = [row for row in ws.iter_rows(values_only=True) if any(v is not None for v in row)]
                    wb.close()

                    if len(sheet_rows) < 2:
                        await spec_repo.update_status(upload.id, UploadStatus.completed)
                        await session.commit()
                        await publish_progress(0, 0, "completed", "В файле нет строк данных")
                        logger.info("Обработка спецификации: в файле нет строк данных")
                        return {"upload_id": upload_id, "processed": 0, "total": 0, "status": "completed"}

                    headers = [str(h) if h is not None else "" for h in sheet_rows[0]]
                    rows_data = sheet_rows[1:]

                    # Индексы колонок по маппингу: роль → номер колонки в листе
                    role_keys = {
                        "name_column": "name",
                        "quantity_column": "quantity",
                        "unit_column": "unit",
                        "price_column": "price",
                    }
                    col_idx: dict[str, int] = {}
                    for map_key, role in role_keys.items():
                        title = column_mapping.get(map_key)
                        if title and title in headers:
                            col_idx[role] = headers.index(title)

                    def cell(row: tuple, role: str) -> Any:
                        """Значение колонки роли в строке (None, если колонки нет)."""
                        idx = col_idx.get(role)
                        if idx is None or idx >= len(row):
                            return None
                        return row[idx]

                    total = len(rows_data)
                    processed = 0
                    logger.info("Обработка спецификации: строк данных — %d", total)

                    for i in range(0, total, BATCH_SIZE_SPEC):
                        batch = rows_data[i : i + BATCH_SIZE_SPEC]
                        for offset, row in enumerate(batch):
                            row_num = i + offset + 2  # 1-индексация, +1 на строку заголовков
                            raw_name = str(cell(row, "name") or "").strip() or str(row[0] or "").strip()
                            if not raw_name:
                                continue  # Пустая строка не участвует в матчинге

                            match_result = await matching_svc.match_row(raw_name=raw_name)
                            tier = match_result["tier"]
                            matched_id = (
                                match_result["matched_item"]["id"] if match_result["matched_item"] else None
                            )

                            if tier == "unmatched":
                                match_type_enum, row_status = MatchType.unmatched, RowStatus.unmatched
                            elif tier == "top_n":
                                match_type_enum, row_status = MatchType.top_n, RowStatus.matched
                            else:
                                match_type_enum, row_status = MatchType.auto, RowStatus.matched

                            await spec_repo.create_row(
                                upload_id=UUID(upload_id),
                                row_number=row_num,
                                raw_data={
                                    "raw_name": raw_name,
                                    "quantity": _json_value(cell(row, "quantity")),
                                    "unit": _json_value(cell(row, "unit")),
                                    "price": _json_value(cell(row, "price")),
                                },
                                matched_item_id=UUID(matched_id) if matched_id else None,
                                match_type=match_type_enum.value,
                                status=row_status.value,
                            )

                            processed += 1

                            await redis_pubsub.publish(
                                channel,
                                RowMatchEvent(
                                    upload_id=upload_id,
                                    seq=await next_seq(),
                                    row_number=row_num,
                                    raw_name=raw_name,
                                    matched_item_id=matched_id,
                                    match_type=tier,
                                    status=row_status.value,
                                    score=match_result["score"],
                                    message=f"Строка {row_num}: {tier}",
                                ).model_dump_json(),
                                buffered=True,
                            )

                        # Прогресс виден в UI до окончания обработки всего файла
                        await session.commit()
                        await publish_progress(processed, total, "processing", f"Обработано {processed}/{total} строк")
                        logger.info("Обработка спецификации: обработано %d/%d строк", processed, total)

                    await spec_repo.update_status(upload.id, UploadStatus.completed)
                    await session.commit()
                    await publish_progress(processed, total, "completed", f"Обработано {processed}/{total} строк")
                    logger.info("Обработка спецификации: завершена, %d/%d строк", processed, total)

                    return {
                        "upload_id": upload_id,
                        "processed": processed,
                        "total": total,
                        "status": "completed",
                    }

        except Exception as exc:
            async with async_session_factory() as session_failed:
                failed_repo = SpecificationRepository(session_failed)
                upload = await failed_repo.get_by_id(UUID(upload_id))
                if upload is not None:
                    await failed_repo.update_status(upload.id, UploadStatus.failed)
                    await session_failed.commit()
            await publish_progress(0, 0, "error", str(exc))
            logger.exception("Обработка спецификации: ошибка, статус failed")
            raise
        finally:
            await redis_pubsub.close()

    token = upload_id_var.set(upload_id)
    try:
        return _run_async(_run)
    finally:
        upload_id_var.reset(token)
