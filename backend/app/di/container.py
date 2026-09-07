"""Сборка dishka-контейнера приложения."""

from dishka import make_async_container

from app.di.providers import (
    DbSessionProvider,
    EmbeddingProvider,
    LlmProvider,
    MinioProvider,
    RedisProvider,
    RepositoryProvider,
    SecurityProvider,
    ServiceProvider,
    SettingsProvider,
)


def create_container() -> object:
    """Создать и настроить async-контейнер dishka для FastAPI."""
    container = make_async_container(
        SettingsProvider(),
        DbSessionProvider(),
        RedisProvider(),
        RepositoryProvider(),
        SecurityProvider(),
        MinioProvider(),
        EmbeddingProvider(),
        LlmProvider(),
        ServiceProvider(),
    )
    return container
