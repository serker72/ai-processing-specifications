"""Структурированное JSON-логирование приложения.

Единый формат записи — одна JSON-строка с полями timestamp/level/logger/message
и контекстным идентификатором: worker пишет `upload_id` таски, backend —
`request_id` HTTP-запроса. Оба идентификатора кладутся в ContextVar, а в запись
их подставляет фильтр, поэтому передавать их в каждый вызов logger не нужно.

Логи uvicorn (его собственные logger'ы `uvicorn*` с propagate=False) этот модуль
не трогает: структурируются только application-логи самого приложения.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Идентификатор обрабатываемой загрузки в контексте текущей Celery-таски.
upload_id_var: ContextVar[str | None] = ContextVar("upload_id", default=None)

# Идентификатор HTTP-запроса (X-Request-ID) в контексте текущего запроса backend.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Значение идентификатора для записей вне соответствующего контекста.
NO_ID = "-"

# Длина request_id: nginx $request_id — 32 hex-символа (16 байт), при отсутствии
# заголовка backend генерирует значение в том же формате.
REQUEST_ID_HEX_LENGTH = 32


class UploadIdFilter(logging.Filter):
    """Добавить в запись текущий upload_id из контекста таски."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.upload_id = upload_id_var.get() or NO_ID
        return True


class RequestIdFilter(logging.Filter):
    """Добавить в запись текущий request_id из контекста запроса."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or NO_ID
        return True


class JsonFormatter(logging.Formatter):
    """Сериализовать запись лога в одну JSON-строку.

    `context_fields` — имена атрибутов, которые фильтры кладут в запись
    (например, `upload_id` для worker или `request_id` для backend). Отсутствующие
    поля пишутся как `-`, чтобы формат строки был стабильным.
    """

    def __init__(self, context_fields: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._context_fields = context_fields

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        for field in self._context_fields:
            payload[field] = getattr(record, field, NO_ID)
        payload["message"] = record.getMessage()
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_root_logging(filters: list[logging.Filter], context_fields: tuple[str, ...]) -> None:
    """Настроить root-логгер на JSON-вывод (один handler, без дублей).

    Повторный вызов безопасен: прежние handler'ы снимаются, поэтому записи не
    дублируются при переимпорте модуля.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(context_fields=context_fields))
    for log_filter in filters:
        handler.addFilter(log_filter)
    root.addHandler(handler)


def configure_worker_logging() -> None:
    """JSON-логи worker: контекстное поле — upload_id таски."""
    _configure_root_logging([UploadIdFilter()], ("upload_id",))


def configure_backend_logging() -> None:
    """JSON-логи backend: контекстное поле — request_id HTTP-запроса.

    Вызывается при импорте `app.main`; uvicorn-логгеры (`uvicorn*`) не
    затрагиваются — структурируются только application-логи приложения.
    """
    _configure_root_logging([RequestIdFilter()], ("request_id",))
