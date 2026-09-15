import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    """Роли пользователей системы."""

    admin = "admin"
    manager = "manager"


class User(Base):
    """Пользователь системы (администратор или менеджер)."""

    __tablename__ = "users"
    __table_args__ = ({"comment": "Пользователи системы"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор пользователя"
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, comment="Адрес электронной почты")
    password_hash: Mapped[str] = mapped_column(String(255), comment="Хэш пароля")
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="tp_user_role"), default=UserRole.manager, comment="Роль пользователя"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )


class Device(Base):
    """Fingerprint-устройство, с которого выполнялся вход (реестр для блокировки)."""

    __tablename__ = "devices"
    __table_args__ = ({"comment": "Зарегистрированные fingerprint-устройства"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор устройства"
    )
    fingerprint_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="SHA-256 хэш fingerprint устройства"
    )
    blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Заблокирован ли вход с устройства"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время первого входа с устройства"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время последнего входа с устройства"
    )


class CatalogItem(Base):
    """Номенклатура каталога, загруженная из прайс-листов."""

    __tablename__ = "catalog_items"
    __table_args__ = (
        # HNSW-индекс для векторного поиска по косинусной дистанции (<=>)
        Index(
            "ix_catalog_items_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("uq_catalog_items_sku_name", "sku", "name", unique=True),
        {"comment": "Номенклатура каталога (из прайс-листов поставщиков)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор позиции каталога"
    )
    sku: Mapped[str] = mapped_column(String(255), index=True, comment="Артикул (SKU)")
    name: Mapped[str] = mapped_column(Text, comment="Наименование позиции")
    unit: Mapped[str | None] = mapped_column(String(32), comment="Единица измерения")
    price: Mapped[float | None] = mapped_column(comment="Цена за единицу")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768), comment="Эмбеддинг наименования (768-dim, multilingual-e5-base)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="Время последнего обновления"
    )


class UploadStatus(str, enum.Enum):
    """Статус обработки загруженного файла."""

    pending = "pending"
    mapping_predicted = "mapping_predicted"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class PriceListUpload(Base):
    """Сессия загрузки прайс-листа администратором."""

    __tablename__ = "price_list_uploads"
    __table_args__ = (
        # История отдаётся фильтром по статусу и сортировкой по времени загрузки.
        Index("ix_price_list_uploads_status_created_at", "status", text("created_at DESC")),
        {"comment": "Сессии загрузки прайс-листов администратором"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор сессии загрузки"
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), comment="Идентификатор администратора, загрузившего файл"
    )
    file_key: Mapped[str] = mapped_column(Text, comment="Ключ объекта файла в MinIO (S3)")
    column_mapping: Mapped[dict | None] = mapped_column(JSONB, comment="Маппинг колонок прайс-листа")
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="tp_upload_status"), default=UploadStatus.pending, comment="Статус обработки файла"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )

    admin: Mapped[User] = relationship()


class SpecificationUpload(Base):
    """Сессия загрузки спецификации клиента менеджером."""

    __tablename__ = "specification_uploads"
    __table_args__ = ({"comment": "Сессии загрузки спецификаций клиентов менеджером"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор сессии загрузки"
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), comment="Идентификатор менеджера, загрузившего файл"
    )
    file_key: Mapped[str] = mapped_column(Text, comment="Ключ объекта файла в MinIO (S3)")
    column_mapping: Mapped[dict | None] = mapped_column(JSONB, comment="Маппинг колонок спецификации")
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="tp_upload_status"), default=UploadStatus.pending, comment="Статус обработки файла"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )

    manager: Mapped[User] = relationship()


class MatchType(str, enum.Enum):
    """Тип результата матчинга строки спецификации."""

    auto = "auto"  # Tier 1: точное совпадение по словарю
    top_n = "top_n"  # Tier 2: варианты из векторного поиска
    unmatched = "unmatched"  # Tier 3: не найдено


class RowStatus(str, enum.Enum):
    """Статус строки спецификации в рабочем процессе менеджера."""

    pending = "pending"
    processing = "processing"  # обработка Matching Engine
    matched = "matched"
    unmatched = "unmatched"  # не найдено в каталоге
    confirmed = "confirmed"  # подтверждено менеджером
    excluded = "excluded"  # исключено менеджером


class SpecificationRow(Base):
    """Строка спецификации клиента с результатом матчинга."""

    __tablename__ = "specification_rows"
    __table_args__ = ({"comment": "Строки спецификаций клиентов с результатами матчинга"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор строки"
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("specification_uploads.id", ondelete="CASCADE"),
        index=True,
        comment="Идентификатор сессии загрузки спецификации",
    )
    row_number: Mapped[int] = mapped_column(comment="Порядковый номер строки в файле")
    raw_data: Mapped[dict] = mapped_column(JSONB, comment="Исходные данные строки из файла")
    matched_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_items.id"), comment="Идентификатор сопоставленной позиции каталога"
    )
    match_type: Mapped[MatchType | None] = mapped_column(
        Enum(MatchType, name="tp_match_type"), comment="Тип результата матчинга (Tier 1/2/3)"
    )
    status: Mapped[RowStatus] = mapped_column(
        Enum(RowStatus, name="tp_row_status"), default=RowStatus.pending, comment="Статус строки"
    )

    upload: Mapped[SpecificationUpload] = relationship()
    matched_item: Mapped[CatalogItem | None] = relationship()


class HistoricalMatch(Base):
    """Словарь подтверждённых совпадений для Tier-1 матчинга."""

    __tablename__ = "historical_matches"
    __table_args__ = ({"comment": "Словарь подтверждённых совпадений (Tier-1 матчинг)"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор записи"
    )
    raw_name_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="SHA-256 хэш исходного наименования"
    )
    raw_name: Mapped[str] = mapped_column(Text, comment="Исходное наименование из спецификации")
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id"), comment="Идентификатор подтверждённой позиции каталога"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )

    catalog_item: Mapped[CatalogItem] = relationship()


class ProposalTemplate(Base):
    """Шаблон коммерческого предложения (HTML/Jinja2)."""

    __tablename__ = "proposal_templates"
    __table_args__ = (
        Index("uq_proposal_templates_start_date", "start_date", unique=True),
        {"comment": "Шаблоны коммерческих предложений"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Идентификатор шаблона"
    )
    name: Mapped[str] = mapped_column(String(255), comment="Название шаблона")
    html_key: Mapped[str] = mapped_column(Text, comment="Ключ файла шаблона в MinIO (HTML/Jinja2)")
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="Дата начала действия шаблона"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Время создания записи"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="Время последнего обновления"
    )
