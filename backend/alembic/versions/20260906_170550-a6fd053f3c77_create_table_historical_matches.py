"""create table historical_matches

Revision ID: a6fd053f3c77
Revises: 2aa8ca5bea0a
Create Date: 2026-09-06 17:05:46.306485

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6fd053f3c77"
down_revision: str | Sequence[str] | None = "2aa8ca5bea0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "historical_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор записи"),
        sa.Column(
            "raw_name_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 хэш исходного наименования",
        ),
        sa.Column("raw_name", sa.Text(), nullable=False, comment="Исходное наименование из спецификации"),
        sa.Column(
            "catalog_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор подтверждённой позиции каталога",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Время создания записи",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historical_matches")),
        sa.UniqueConstraint("raw_name_hash", name=op.f("uq_historical_matches_raw_name_hash")),
        comment="Словарь подтверждённых совпадений (Tier-1 матчинг)",
    )

    op.create_foreign_key(
        op.f("fk_historical_matches_catalog_item_id_catalog_items"),
        "historical_matches",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("historical_matches")
