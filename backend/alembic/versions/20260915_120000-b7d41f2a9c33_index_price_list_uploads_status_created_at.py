"""create index price_list_uploads.status_created_at

Revision ID: b7d41f2a9c33
Revises: c9cc1eb10b21
Create Date: 2026-09-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b7d41f2a9c33'
down_revision: str | Sequence[str] | None = 'c9cc1eb10b21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Индекс для истории загрузок прайс-листов.

    История фильтруется по статусу и сортируется по времени загрузки —
    составной индекс закрывает оба запроса (фильтр и сортировку).
    """
    op.create_index(
        op.f("ix_price_list_uploads_status_created_at"),
        "price_list_uploads",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Удаляет индекс истории загрузок прайс-листов."""
    op.drop_index(op.f("ix_price_list_uploads_status_created_at"), table_name="price_list_uploads")
