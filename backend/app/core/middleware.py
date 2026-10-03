"""ASGI-middleware: идентификатор запроса для структурированных логов.

`RequestIdMiddleware` кладёт в ContextVar `request_id_var` значение заголовка
`X-Request-ID`, который прокидывает nginx (`$request_id` — 32 hex-символа). Если
заголовка нет (прямой запрос к backend, тесты), идентификатор генерируется в том
же формате. Значение возвращается клиенту в ответном заголовке `X-Request-ID`,
что упрощает сопоставление логов с запросами.

Middleware реализован как чистый ASGI (а не `BaseHTTPMiddleware`): запись в
ContextVar происходит в том же контексте, что и вызов эндпоинта, поэтому
application-логи внутри обработчика видят request_id.
"""

import secrets

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging_config import REQUEST_ID_HEX_LENGTH, request_id_var

# Заголовок, которым обмениваются nginx и backend.
REQUEST_ID_HEADER = "X-Request-ID"


def generate_request_id() -> str:
    """Сгенерировать request_id в формате nginx `$request_id` (32 hex-символа)."""
    return secrets.token_hex(REQUEST_ID_HEX_LENGTH // 2)


class RequestIdMiddleware:
    """Установить request_id в контекст запроса и вернуть его в ответе."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # WebSocket/lifespan не обслуживаем: пропускаем без изменений.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or generate_request_id()
        token = request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
