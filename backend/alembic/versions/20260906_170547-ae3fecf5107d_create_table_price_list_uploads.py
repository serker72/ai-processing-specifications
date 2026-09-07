"""create table price_list_uploads

Revision ID: ae3fecf5107d
Revises: afb827ee6962
Create Date: 2026-09-06 17:05:45.556248

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.models import UploadStatus

# revision identifiers, used by Alembic.
revision: str = "ae3fecf5107d"
down_revision: str | Sequence[str] | None = "afb827ee6962"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "price_list_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор сессии загрузки"),
        sa.Column(
            "admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор администратора, загрузившего файл",
        ),
        sa.Column("file_key", sa.Text(), nullable=False, comment="Ключ объекта файла в MinIO (S3)"),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=True, comment="Маппинг колонок прайс-листа"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_list_uploads")),
        comment="Сессии загрузки прайс-листов администратором",
    )

    op.create_foreign_key(
        op.f("fk_price_list_uploads_admin_id_users"),
        "price_list_uploads",
        "users",
        ["admin_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("price_list_uploads")
    op.execute("DROP TYPE IF EXISTS tp_upload_status")
