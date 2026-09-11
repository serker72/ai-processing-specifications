"""Celery-таски для фоновой векторизации каталога и обработки спецификаций (Модули 3 и 5)."""

import asyncio
from typing import Any

from app.schemas.sse_events import ProgressEvent, RowMatchEvent
from app.worker import celery_app

BATCH_SIZE = 500  # Строк в одном батче


# Получаем экземпляр celery_app для регистрации таски
_celery_app = celery_app


@_celery_app.task(bind=True, name="catalog.vectorize")
def vectorize_catalog(self: Any, upload_id: str) -> dict:
    """Фоновая векторизация каталога из прайс-листа.

    Батчами по BATCH_SIZE строк:
    1. Читает файл из MinIO через PriceListService.
    2. Для каждой строки вызывает EmbeddingService (768-dim).
    3. Сохраняет embedding в CatalogItem.
    """

    async def _run() -> dict:
        from uuid import UUID

        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.models.models import CatalogItem
        from app.repositories.price_list_repository import PriceListRepository
        from app.services.embedding_service import EmbeddingService
        from app.services.price_list_service import PriceListService

        container = create_container()
        async with container() as c, async_session_factory() as session:
            price_list_repo = PriceListRepository(session)
            upload = await price_list_repo.get_by_id(UUID(upload_id))
            if not upload:
                return {"error": "upload not found", "upload_id": upload_id}

            file_key = upload.file_key  # ключ в MinIO
            column_mapping = upload.column_mapping
            if not column_mapping:
                return {"error": "no column_mapping", "upload_id": upload_id}

            # 1. Прочитать данные прайс-листа (файл уже в MinIO)
            minio_svc = await c.get(PriceListService)
            rows = await minio_svc._parse_pricelist(file_key, column_mapping)

            # 2. Векторизация батчами
            embedding_svc = await c.get(EmbeddingService)

            total = len(rows)
            for i in range(0, total, BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                embeddings = embedding_svc.embed_passages([r["description"] for r in batch])

                items = [
                    CatalogItem(
                        sku=r["sku"],
                        name=r["name"],
                        price=r.get("price"),
                        embedding=list(emb),
                    )
                    for r, emb in zip(batch, embeddings)
                ]
                session.add_all(items)
                await session.flush()

            await session.commit()

            return {
                "upload_id": upload_id,
                "total_rows": total,
                "status": "completed",
            }

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


BATCH_SIZE_SPEC = 100  # Строк спецификации в одном батче


@_celery_app.task(bind=True, name="specification.process")
def process_specification(
    self: Any,
    upload_id: str,
    manager_id: str,
) -> dict:
    """Фоновая обработка строк спецификации через Matching Engine.

    Алгоритм:
    1. Читает Excel из MinIO по column_mapping.
    2. Для каждой строки вызывает MatchingEngine.
    3. Сохраняет результат в SpecificationRow.
    4. Публикует прогресс в Redis Pub/Sub (channel: spec_{upload_id}).
    """

    async def _run() -> dict:
        from uuid import UUID

        from app.db.session import async_session_factory
        from app.di.container import create_container
        from app.models.models import MatchType, RowStatus
        from app.repositories.matching_repository import MatchingRepository
        from app.repositories.specification_repository import SpecificationRepository
        from app.services.embedding_service import EmbeddingService
        from app.services.matching_service import MatchingService
        from app.services.minio_service import MinioService
        from app.worker.redis_pubsub import RedisPubSub

        container = create_container()
        redis_pubsub = RedisPubSub()
        channel = f"spec_{upload_id}"

        try:
            async with container() as c, async_session_factory() as session:
                spec_repo = SpecificationRepository(session)
                matching_repo = MatchingRepository(session)
                embedding_svc = await c.get(EmbeddingService)
                matching_svc = MatchingService(matching_repo, embedding_svc)
                minio_svc = await c.get(MinioService)

                # 1. Получить upload и column_mapping
                upload = await spec_repo.get_by_id(UUID(upload_id))
                if not upload:
                    await redis_pubsub.publish(channel, ProgressEvent(
                        upload_id=upload_id,
                        processed=0,
                        total=0,
                        status="error",
                        message="Upload not found",
                    ).model_dump_json())
                    return {"error": "upload not found", "upload_id": upload_id}

                column_mapping = upload.column_mapping
                if not column_mapping:
                    await redis_pubsub.publish(channel, ProgressEvent(
                        upload_id=upload_id,
                        processed=0,
                        total=0,
                        status="error",
                        message="No column_mapping",
                    ).model_dump_json())
                    return {"error": "no column_mapping", "upload_id": upload_id}

                # 2. Прочитать данные Excel из MinIO
                file_key = upload.file_key
                wb = await minio_svc.download_workbook(file_key)
                ws = wb.active
                rows_data = []
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if any(cell is not None for cell in row):
                        rows_data.append(row)

                total = len(rows_data)
                name_col = column_mapping.get("name_column")
                qty_col = column_mapping.get("quantity_column")
                unit_col = column_mapping.get("unit_column")
                price_col = column_mapping.get("price_column")

                # Найти индексы колонок по заголовку
                headers = [str(cell) for cell in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
                col_indices = {}
                for col_key in (name_col, qty_col, unit_col, price_col):
                    if col_key:
                        try:
                            idx = headers.index(col_key)
                            col_indices[col_key] = idx
                        except ValueError:
                            pass

                # 3. Обработка строк батчами
                processed = 0
                for i in range(0, total, BATCH_SIZE_SPEC):
                    batch = rows_data[i : i + BATCH_SIZE_SPEC]
                    for row_idx, row in enumerate(batch):
                        row_num = i + row_idx + 2  # 1-indexed, +1 for header
                        raw_name = str(
                            row[col_indices.get("name_column", 0)]
                        ) if col_indices.get("name_column") is not None else str(row[0])

                        # Matching Engine
                        match_result = await matching_svc.match_row(raw_name=raw_name)

                        # Определить тип матчинга
                        tier = match_result["tier"]
                        if tier == "auto":
                            match_type_enum = MatchType.auto
                            row_status = RowStatus.matched
                        elif tier == "top_n":
                            match_type_enum = MatchType.top_n
                            row_status = RowStatus.matched
                        else:
                            match_type_enum = MatchType.unmatched
                            row_status = RowStatus.unmatched

                        matched_item_id = (
                            match_result["matched_item"]["id"]
                            if match_result["matched_item"]
                            else None
                        )

                        # Сохранить строку
                        await spec_repo.create_row(
                            upload_id=UUID(upload_id),
                            row_number=row_num,
                            raw_data={
                                "raw_name": raw_name,
                                "quantity": (
                                    row[col_indices["quantity_column"]]
                                    if "quantity_column" in col_indices
                                    else None
                                ),
                                "unit": (
                                    row[col_indices["unit_column"]]
                                    if "unit_column" in col_indices
                                    else None
                                ),
                                "price": (
                                    row[col_indices["price_column"]]
                                    if "price_column" in col_indices
                                    else None
                                ),
                            },
                            matched_item_id=matched_item_id,
                            match_type=match_type_enum.value,
                            status=row_status.value,
                        )

                        processed += 1

                        # Публикация прогресса
                        await redis_pubsub.publish(channel, RowMatchEvent(
                            upload_id=upload_id,
                            row_number=row_num,
                            raw_name=raw_name,
                            matched_item_id=matched_item_id,
                            match_type=tier,
                            status=row_status.value,
                            score=match_result["score"],
                            message=(
                                f"Processed row {row_num}: {tier}"
                                if tier != "unmatched"
                                else f"Unmatched row {row_num}"
                            ),
                        ).model_dump_json())

                    # Обновить статус upload
                    await spec_repo.update_status(
                        UUID(upload_id),
                        RowStatus.processing if processed < total else RowStatus.matched,
                    )

                await redis_pubsub.publish(channel, ProgressEvent(
                    upload_id=upload_id,
                    processed=processed,
                    total=total,
                    status="completed",
                    message=f"Processed {processed}/{total} rows",
                ).model_dump_json())

                return {
                    "upload_id": upload_id,
                    "processed": processed,
                    "total": total,
                    "status": "completed",
                }

        except Exception as e:
            import traceback
            traceback.print_exc()
            await redis_pubsub.publish(channel, ProgressEvent(
                upload_id=upload_id,
                processed=0,
                total=0,
                status="error",
                message=str(e),
            ).model_dump_json())
            raise

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

