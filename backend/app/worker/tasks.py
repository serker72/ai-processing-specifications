"""Celery-таски для фоновой векторизации каталога (Модуль 3)."""

import asyncio
from typing import Any

# Импортируем celery_app напрямую из модуля, а не из __init__.py
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
