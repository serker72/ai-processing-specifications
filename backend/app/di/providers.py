"""Провайдеры зависимостей приложения (dishka).

Один провайдер на слой: настройки, сессии БД, репозитории, сервисы.
"""

from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import async_session_factory
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.price_list_repository import PriceListRepository
from app.repositories.proposal_template_repository import ProposalTemplateRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.specification_repository import SpecificationRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.catalog_service import CatalogService
from app.services.device_service import DeviceService
from app.services.embedding_service import EmbeddingService
from app.services.excel_preview_service import ExcelPreviewService
from app.services.llm_service import LlmService
from app.services.matching_service import MatchingService
from app.services.minio_service import MinioService
from app.services.price_list_service import PriceListService
from app.services.proposal_template_service import ProposalTemplateService
from app.services.security import SecurityService
from app.services.session_admin_service import SessionAdminService
from app.services.specification_service import SpecificationService
from app.services.user_service import UserService


class SettingsProvider(Provider):
    """Провайдер конфигурации: единый кэшированный Settings на всё приложение."""

    scope = Scope.APP

    @provide
    def provide_settings(self) -> Settings:
        return get_settings()


class DbSessionProvider(Provider):
    """Провайдер сессий БД: одна сессия на запрос (unit-of-work).

    Коммит выполняется автоматически при успешном завершении запроса,
    rollback — при исключении. Репозитории делают только flush.
    """

    scope = Scope.APP

    @provide(scope=Scope.REQUEST)
    async def provide_session(self) -> AsyncIterator[AsyncSession]:
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @provide
    def provide_session_factory(self) -> async_sessionmaker[AsyncSession]:
        return async_session_factory


class RepositoryProvider(Provider):
    """Провайдер репозиториев: scope = Scope.REQUEST (один экземпляр на запрос)."""

    scope = Scope.REQUEST

    @provide
    def provide_user_repository(self, session: AsyncSession) -> UserRepository:
        return UserRepository(session)

    @provide
    def provide_session_repository(self, redis: Redis) -> SessionRepository:
        return SessionRepository(redis)

    @provide
    def provide_device_repository(self, session: AsyncSession) -> DeviceRepository:
        return DeviceRepository(session)

    @provide
    def provide_catalog_repository(self, session: AsyncSession) -> CatalogRepository:
        return CatalogRepository(session)

    @provide
    def provide_price_list_repository(self, session: AsyncSession) -> PriceListRepository:
        return PriceListRepository(session)

    @provide
    def provide_matching_repository(self, session: AsyncSession) -> MatchingRepository:
        return MatchingRepository(session)

    @provide
    def provide_proposal_template_repository(self, session: AsyncSession) -> ProposalTemplateRepository:
        return ProposalTemplateRepository(session)


class MinioProvider(Provider):
    """Провайдер MinIO: Singleton на процесс (лёгкий клиент)."""

    scope = Scope.APP

    @provide
    def provide_minio_service(self, settings: Settings) -> MinioService:
        return MinioService(settings)


class EmbeddingProvider(Provider):
    """Провайдер эмбеддингов: Singleton на процесс (модель грузится один раз)."""

    scope = Scope.APP

    @provide
    def provide_embedding_service(self, settings: Settings) -> EmbeddingService:
        return EmbeddingService(settings)


class LlmProvider(Provider):
    """Провайдер LLM: Singleton на процесс (лёгкий клиент litellm)."""

    scope = Scope.APP

    @provide
    def provide_llm_service(self, settings: Settings) -> LlmService:
        return LlmService(settings)


class RedisProvider(Provider):
    """Провайдер Redis: один клиент на процесс."""

    scope = Scope.APP

    @provide
    def provide_redis(self) -> Redis:
        import redis.asyncio as aioredis

        from app.core.config import get_settings

        settings = get_settings()
        return aioredis.from_url(settings.redis.url, decode_responses=False)


class SecurityProvider(Provider):
    """Провайдер сервисов безопасности: авторизация, JWT, сессии."""

    scope = Scope.REQUEST

    @provide
    def provide_security_service(self, settings: Settings) -> SecurityService:
        return SecurityService(settings)


class ServiceProvider(Provider):
    """Провайдеры сервисов: бизнес-логика приложения."""

    scope = Scope.REQUEST

    @provide
    def provide_auth_service(
        self,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        security_service: SecurityService,
        settings: Settings,
        device_repository: DeviceRepository,
    ) -> AuthService:
        return AuthService(user_repository, session_repository, security_service, settings, device_repository)

    @provide
    def provide_user_service(self, user_repository: UserRepository) -> UserService:
        return UserService(user_repository)

    @provide
    def provide_session_admin_service(
        self,
        session_repository: SessionRepository,
        user_repository: UserRepository,
        security_service: SecurityService,
    ) -> SessionAdminService:
        return SessionAdminService(session_repository, user_repository, security_service)

    @provide
    def provide_device_service(
        self,
        device_repository: DeviceRepository,
        session_admin_service: SessionAdminService,
    ) -> DeviceService:
        return DeviceService(device_repository, session_admin_service)

    @provide
    def provide_catalog_service(self, catalog_repository: CatalogRepository) -> CatalogService:
        return CatalogService(catalog_repository)

    @provide
    def provide_price_list_service(
        self,
        minio_service: MinioService,
        llm_service: LlmService,
        price_list_repository: PriceListRepository,
    ) -> PriceListService:
        return PriceListService(minio_service, ExcelPreviewService(), llm_service, price_list_repository)

    @provide
    def provide_matching_service(
        self,
        matching_repo: MatchingRepository,
        embedding_service: EmbeddingService,
    ) -> MatchingService:
        return MatchingService(matching_repo, embedding_service)

    @provide
    def provide_specification_repository(
        self, session: AsyncSession
    ) -> SpecificationRepository:
        return SpecificationRepository(session)

    @provide
    def provide_specification_service(
        self,
        minio_service: MinioService,
        llm_service: LlmService,
        specification_repo: SpecificationRepository,
    ) -> SpecificationService:
        return SpecificationService(
            minio_service,
            ExcelPreviewService(),
            llm_service,
            specification_repo,
        )

    @provide
    def provide_proposal_template_service(
        self,
        minio_service: MinioService,
        proposal_template_repo: ProposalTemplateRepository,
    ) -> ProposalTemplateService:
        return ProposalTemplateService(proposal_template_repo, minio_service)
