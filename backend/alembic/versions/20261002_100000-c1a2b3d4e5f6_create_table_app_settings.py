"""create table app_settings

Revision ID: c1a2b3d4e5f6
Revises: b7d41f2a9c33
Create Date: 2026-10-02 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: str | Sequence[str] | None = "b7d41f2a9c33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт таблицу системных настроек (singleton)."""
    op.create_table(
        "app_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_name", sa.String(255), nullable=True),
        sa.Column("seller_inn", sa.String(12), nullable=True),
        sa.Column("seller_kpp", sa.String(9), nullable=True),
        sa.Column("seller_address", sa.Text(), nullable=True),
        sa.Column("seller_phone", sa.String(32), nullable=True),
        sa.Column("seller_email", sa.String(255), nullable=True),
        sa.Column("bank_account", sa.String(20), nullable=True),
        sa.Column("bank_name", sa.String(255), nullable=True),
        sa.Column("bank_bik", sa.String(9), nullable=True),
        sa.Column("corr_account", sa.String(20), nullable=True),
        sa.Column("signer_name", sa.String(255), nullable=True),
        sa.Column("signer_position", sa.String(255), nullable=True),
        sa.Column("vat_rate", sa.Numeric(5, 2), server_default=sa.text("20.00"), nullable=False),
        sa.Column("vat_included", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
        comment="Системные настройки (реквизиты продавца, НДС)",
    )


def downgrade() -> None:
    """Удаляет таблицу системных настроек."""
    op.drop_table("app_settings")
