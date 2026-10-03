"""Структурированное логирование worker: JSON-записи с upload_id таски.

Каждая строка лога — отдельный JSON-объект с полями timestamp/level/logger/
upload_id/message. Идентификатор загрузки кладётся в ContextVar в начале
Celery-таски и подставляется в записи фильтром, поэтому его не нужно передавать
в каждый вызов logger вручную.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Идентификатор обрабатываемой загрузки в контексте текущей таски.
upload_id_var: ContextVar[str | None] = ContextVar("upload_id", default=None)

# Значение upload_id для записей вне таски (старт воркера, служебные сообщения).
NO_UPLOAD_ID = "-"


class UploadIdFilter(logging.Filter):
    """Добавить в запись текущий upload_id из контекста таски."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.upload_id = upload_id_var.get() or NO_UPLOAD_ID
        return True


class JsonFormatter(logging.Formatter):
    """Сериализовать запись лога в одну JSON-строку."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "upload_id": getattr(record, "upload_id", NO_UPLOAD_ID),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_worker_logging(level: int = logging.INFO) -> None:
    """Настроить root-логгер worker на JSON-вывод (один handler, без дублей).

    Повторный вызов безопасен: прежние handler'ы снимаются, поэтому записи не
    дублируются при переимпорте модуля.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(UploadIdFilter())
    root.addHandler(handler)
