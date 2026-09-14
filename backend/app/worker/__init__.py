"""Celery-приложение и таски."""

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "worker",
    broker=settings.redis.url,
    backend=settings.redis.url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    imports=("app.worker.tasks",),  # Регистрация тасок при старте воркера
)


@worker_process_init.connect
def init_embedding_model(**kwargs) -> None:
    """Прогрев модели эмбеддингов при старте каждого процесса воркера (Singleton)."""
    from app.services.embedding_service import EmbeddingService

    EmbeddingService(get_settings()).warm_up()
    print("Embedding model warmed up:", settings.embedding.model_name)

# Импортируем таски для регистрации в Celery
from app.worker.tasks import process_specification, vectorize_catalog  # noqa: E402, F401
