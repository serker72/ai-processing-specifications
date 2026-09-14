"""Celery-таски для фоновой векторизации каталога и обработки спецификаций (Модули 3 и 5).

Обе таски работают в собственном event loop (`asyncio.new_event_loop`) и в
собственной сессии БД: коммит выполняется по батчам, чтобы прогресс был виден
подписчикам SSE и списку загрузок ещё до окончания обработки файла.
Статусы загрузки берутся только из `UploadStatus` — `RowStatus` описывает
строку и к статусу файла отношения не имеет.
"""

import asyncio
from typing import Any
from uuid import UUID

from app.schemas.sse_events import ProgressEvent, RowMatchEvent
from app.worker import celery_app

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
        loop.close()


def _json_value(value: Any) -> Any:
    """Значение ячейки Excel → JSON-совместимый тип для raw_data (JSONB).

    Даты и Decimal сериализуются в строку, числа и строки остаются как есть:
    иначе psycopg отклонит весь объект JSONB при вставке строки спецификации.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


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
        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.models.models import UploadStatus
        from app.repositories.catalog_repository import CatalogRepository
        from app.repositories.price_list_repository import PriceListRepository
        from app.services.embedding_service import EmbeddingService
        from app.services.price_list_service import PriceListService

        container = create_container()
        async with container() as c:
            embedding_svc = await c.get(EmbeddingService)
            price_list_svc = await c.get(PriceListService)

            async with async_session_factory() as session:
                price_list_repo = PriceListRepository(session)
                catalog_repo = CatalogRepository(session)

                upload = await price_list_repo.get_by_id(UUID(upload_id))
                if upload is None:
                    return {"error": "upload not found", "upload_id": upload_id}
                if not upload.column_mapping:
                    return {"error": "no column_mapping", "upload_id": upload_id}

                file_key = upload.file_key
                column_mapping = upload.column_mapping
                await price_list_repo.update_status(upload.id, UploadStatus.processing)
                await session.commit()

                total = 0
                try:
                    rows = await price_list_svc.parse_pricelist(file_key, column_mapping)
                    total = len(rows)

                    for i in range(0, total, BATCH_SIZE):
                        batch = rows[i : i + BATCH_SIZE]
                        embeddings = embedding_svc.embed_passages([r["description"] for r in batch])
                        items = [
                            {
                                "sku": r["sku"],
                                "name": r["name"],
                                "unit": r.get("unit"),
                                "price": r.get("price"),
                                "embedding": list(emb),
                            }
                            for r, emb in zip(batch, embeddings, strict=True)
                        ]
                        # UPSERT: повторная загрузка прайса обновляет позиции,
                        # а не падает на уникальном индексе (sku, name)
                        await catalog_repo.upsert_batch(items)
                        await session.commit()

                    await price_list_repo.update_status(upload.id, UploadStatus.completed)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    await _mark_failed()
                    raise

                return {"upload_id": upload_id, "total_rows": total, "status": "completed"}

    return _run_async(_run)


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

        async def publish_progress(processed: int, total: int, status: str, message: str) -> None:
            """Опубликовать событие прогресса в канал загрузки."""
            await redis_pubsub.publish(
                channel,
                ProgressEvent(
                    upload_id=upload_id,
                    processed=processed,
                    total=total,
                    status=status,
                    message=message,
                ).model_dump_json(),
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
                        await publish_progress(0, 0, "error", "Загрузка не найдена")
                        return {"error": "upload not found", "upload_id": upload_id}
                    if not upload.column_mapping:
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
                                    row_number=row_num,
                                    raw_name=raw_name,
                                    matched_item_id=matched_id,
                                    match_type=tier,
                                    status=row_status.value,
                                    score=match_result["score"],
                                    message=f"Строка {row_num}: {tier}",
                                ).model_dump_json(),
                            )

                        # Прогресс виден в UI до окончания обработки всего файла
                        await session.commit()
                        await publish_progress(processed, total, "processing", f"Обработано {processed}/{total} строк")

                    await spec_repo.update_status(upload.id, UploadStatus.completed)
                    await session.commit()
                    await publish_progress(processed, total, "completed", f"Обработано {processed}/{total} строк")

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
            raise
        finally:
            await redis_pubsub.close()

    return _run_async(_run)
