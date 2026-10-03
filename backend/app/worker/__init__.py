"""Celery-приложение и таски."""

import logging

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings
from app.core.logging_config import configure_worker_logging

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
    # Не перехватывать root-логгер: иначе Celery ставит свой формат и
    # структурированные JSON-записи (configure_worker_logging) теряются.
    worker_hijack_root_logger=False,
    # Не подменять sys.stdout LoggingProxy: иначе StreamHandler JSON-логгера
    # пишет в proxy, а не в реальный stdout контейнера, и записи пропадают.
    worker_redirect_stdouts=False,
)

logger = logging.getLogger(__name__)


@worker_process_init.connect
def init_worker_process(**kwargs) -> None:
    """Настроить JSON-логирование и прогреть модель в каждом процессе воркера.

    Сигнал срабатывает в дочернем процессе пула: настройка не затрагивает
    backend, который тоже импортирует пакет `app.worker` (там логи uvicorn).
    """
    configure_worker_logging()

    from app.services.embedding_service import EmbeddingService

    EmbeddingService(get_settings()).warm_up()
    logger.info("Модель эмбеддингов прогрета: %s", settings.embedding.model_name)



# Импортируем таски для регистрации в Celery
from app.worker.tasks import (  # noqa: F401
    process_specification,
    reembed_catalog_item,
    vectorize_catalog,
)
