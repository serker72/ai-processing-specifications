from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.admin import admin_router
from app.api.v1.manager import manager_router
from app.core.config import get_settings
from app.di.container import create_container

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

app.include_router(api_router, prefix=settings.backend.api_prefix)
app.include_router(admin_router, prefix=settings.backend.api_prefix)
app.include_router(manager_router, prefix=settings.backend.api_prefix)
setup_dishka(create_container(), app=app)


@app.get(settings.backend.api_prefix + "/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
