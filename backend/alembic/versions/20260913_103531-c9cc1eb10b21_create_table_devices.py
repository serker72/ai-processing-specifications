"""create table devices

Revision ID: c9cc1eb10b21
Revises: a1b2c3d4e5f6
Create Date: 2026-09-13 10:35:31.084572

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c9cc1eb10b21'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт таблицу devices."""
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор устройства"),
        sa.Column(
            "fingerprint_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 хэш fingerprint устройства",
        ),
        sa.Column(
            "blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Заблокирован ли вход с устройства",
        ),
        sa.Column(
            "first_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Время первого входа с устройства",
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Время последнего входа с устройства",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        comment="Зарегистрированные fingerprint-устройства",
    )

    op.create_unique_constraint(
        op.f("uq_devices_fingerprint_hash"),
        "devices",
        ["fingerprint_hash"],
    )


def downgrade() -> None:
    """Удаляет таблицу devices."""
    op.drop_table("devices")
