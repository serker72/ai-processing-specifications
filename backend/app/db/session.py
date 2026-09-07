from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.postgres.dsn,
    echo=settings.sqlalchemy.debug,
    pool_size=settings.sqlalchemy.pool_size,
    max_overflow=settings.sqlalchemy.max_overflow,
    pool_recycle=settings.sqlalchemy.pool_recycle,
    pool_pre_ping=settings.sqlalchemy.pool_pre_ping,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
