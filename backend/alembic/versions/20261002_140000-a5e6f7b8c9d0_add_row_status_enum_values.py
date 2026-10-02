"""add missing values to tp_row_status enum

Revision ID: a5e6f7b8c9d0
Revises: f4d5e6a7b8c9
Create Date: 2026-10-02 14:00:00.000000

Дефект схемы: enum tp_row_status был создан по ранней версии RowStatus
(pending/matched/confirmed/excluded), а позже в модели появились
processing и unmatched — без миграции. Воркер Matching Engine пишет
unmatched, поэтому без этих значений обработка спецификаций падает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a5e6f7b8c9d0"
down_revision: str | Sequence[str] | None = "f4d5e6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет недостающие значения статуса строки спецификации."""
    # ALTER TYPE ... ADD VALUE нельзя смешивать с использованием нового значения
    # в той же транзакции — выполняем в autocommit-блоке.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tp_row_status ADD VALUE IF NOT EXISTS 'processing'")
        op.execute("ALTER TYPE tp_row_status ADD VALUE IF NOT EXISTS 'unmatched'")


def downgrade() -> None:
    """Откат не выполняется: значения enum могут использоваться в данных.

    PostgreSQL не поддерживает удаление отдельных значений enum без пересоздания
    типа, а строки со статусом unmatched/processing к моменту отката могут уже
    существовать. Оставляем значения как безвредные.
    """
