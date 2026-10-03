from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.admin import admin_router
from app.api.v1.admin_access import admin_access_router
from app.api.v1.manager import manager_router
from app.core.config import get_settings
from app.core.logging_config import configure_backend_logging
from app.core.middleware import RequestIdMiddleware
from app.di.container import create_container

# Application-логи backend — в JSON. Вызывается до создания приложения, чтобы
# сообщения о старте уже были структурированными; логгеры uvicorn не трогаются.
configure_backend_logging()

settings = get_settings()

app = FastAPI(title="AI Processing Specifications", debug=settings.backend.debug)

# CORS: origin'ы берутся из CORS_ORIGINS (.env). allow_credentials обязателен —
# auth-токены передаются через HttpOnly-куки, без него браузер их не прикладывает.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# request_id из заголовка X-Request-ID (nginx) или сгенерированный — в контекст
# логов и в ответный заголовок. Добавляется последним, чтобы быть внешним слоем
# и проставлять заголовок на все ответы, включая ошибки CORS.
app.add_middleware(RequestIdMiddleware)

app.include_router(api_router, prefix=settings.backend.api_prefix)
app.include_router(admin_router, prefix=settings.backend.api_prefix)
app.include_router(admin_access_router, prefix=settings.backend.api_prefix)
app.include_router(manager_router, prefix=settings.backend.api_prefix)
setup_dishka(create_container(), app=app)


@app.get(settings.backend.api_prefix + "/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
