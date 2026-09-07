from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    """Общие настройки проекта (префикс PROJECT_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="PROJECT_", extra="ignore")

    environment: str = "loc"
    url_scheme: str = "http"
    domain: str = "localhost"
    data_dir: str = "/data"


class PostgresSettings(BaseSettings):
    """Параметры PostgreSQL (префикс POSTGRES_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="POSTGRES_", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "app"
    password: str = "app"
    db: str = "app"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dsn(self) -> str:
        # DSN для psycopg3: postgresql+psycopg://user:password@host:port/dbname
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class SQLAlchemySettings(BaseSettings):
    """Настройки пула соединений SQLAlchemy (префикс SQLALCHEMY_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="SQLALCHEMY_", extra="ignore")

    debug: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle: int = 600
    pool_use_lifo: bool = False
    pool_pre_ping: bool = True


class RedisSettings(BaseSettings):
    """Параметры Redis (префикс REDIS_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"


class MinioSettings(BaseSettings):
    """Параметры MinIO / S3 (префикс MINIO_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="MINIO_", extra="ignore")

    host: str = "localhost"
    port: int = 9000
    bucket: str = "spec-files"
    root_user: str = "minioadmin"
    root_password: str = "minioadmin"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"


class BackendSettings(BaseSettings):
    """Настройки backend-приложения (префикс BACKEND_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="BACKEND_", extra="ignore")

    debug: bool = False
    worker_count: int = 1
    port: int = 8000
    api_prefix: str = "/api/v1"
    base_url: str = "http://localhost"


class CorsSettings(BaseSettings):
    """CORS (переменная CORS_ORIGINS, JSON-список)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    origins: list[str] = Field(default=[], validation_alias="CORS_ORIGINS")


class JWTSettings(BaseSettings):
    """Настройки JWT и auth-кук (префикс JWT_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="JWT_", extra="ignore")

    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    # Secure-куки требуют HTTPS; для локальной разработки по http — False
    cookie_secure: bool = False
    cookie_domain: str | None = None


class EmbeddingSettings(BaseSettings):
    """Настройки локальной модели эмбеддингов (префикс EMBEDDING_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="EMBEDDING_", extra="ignore")

    model_name: str = "intfloat/multilingual-e5-base"
    device: str = "cpu"
    # Размерность векторов модели (должна совпадать с Vector(n) в CatalogItem.embedding)
    dim: int = 768


class LlmSettings(BaseSettings):
    """Настройки LLM через litellm (префикс LLM_).

    Роутинг: provider='openai' -> облачная модель (ключ OPENAI_API_KEY),
    provider='ollama' -> локальная модель Ollama (LLM_OLLAMA_BASE_URL).
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="LLM_", extra="ignore")

    # Провайдер по умолчанию: 'openai' | 'ollama'
    provider: str = "ollama"
    # Имя модели для OpenAI (формат litellm: openai/<model>)
    openai_model: str = "openai/gpt-4o-mini"
    # Имя модели для Ollama (формат litellm: ollama/<model>)
    ollama_model: str = "ollama/qwen2.5:7b"
    ollama_base_url: str = "http://ollama:11434"
    # Параметры генерации
    temperature: float = 0.0
    max_tokens: int = 1024
    # Таймаут запроса к LLM, сек
    request_timeout: int = 60


class OpenAISettings(BaseSettings):
    """Параметры OpenAI API (префикс OPENAI_)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="OPENAI_", extra="ignore")

    api_key: str = ""


class Settings(BaseSettings):
    """Агрегирующий конфиг: группы настроек читают env по своим префиксам."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project: ProjectSettings = Field(default_factory=ProjectSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    sqlalchemy: SQLAlchemySettings = Field(default_factory=SQLAlchemySettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    backend: BackendSettings = Field(default_factory=BackendSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()
