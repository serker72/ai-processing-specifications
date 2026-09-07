"""create table specification_uploads

Revision ID: 81a67f2555e4
Revises: ae3fecf5107d
Create Date: 2026-09-06 17:05:45.801824

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.models import UploadStatus

# revision identifiers, used by Alembic.
revision: str = "81a67f2555e4"
down_revision: str | Sequence[str] | None = "ae3fecf5107d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "specification_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор сессии загрузки"),
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор менеджера, загрузившего файл",
        ),
        sa.Column("file_key", sa.Text(), nullable=False, comment="Ключ объекта файла в MinIO (S3)"),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=True, comment="Маппинг колонок спецификации"),
        sa.Column(
            "status",
            sa.Enum(UploadStatus, name="tp_upload_status"),
            nullable=False,
            comment="Статус обработки файла",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Время создания записи",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specification_uploads")),
        comment="Сессии загрузки спецификаций клиентов менеджером",
    )

    op.create_foreign_key(
        op.f("fk_specification_uploads_manager_id_users"),
        "specification_uploads",
        "users",
        ["manager_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("specification_uploads")
