"""create table users

Revision ID: 98660febdf1e
Revises: 
Create Date: 2026-09-06 17:05:45.050979

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.models import UserRole

# revision identifiers, used by Alembic.
revision: str = "98660febdf1e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Расширение pgvector нужно для векторного поиска по каталогу (CatalogItem.embedding)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор пользователя"),
        sa.Column("email", sa.String(length=255), nullable=False, comment="Адрес электронной почты"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="Хэш пароля"),
        sa.Column("role", sa.Enum(UserRole, name="tp_user_role"), nullable=False, comment="Роль пользователя"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Время создания записи",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        comment="Пользователи системы",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS tp_user_role")
