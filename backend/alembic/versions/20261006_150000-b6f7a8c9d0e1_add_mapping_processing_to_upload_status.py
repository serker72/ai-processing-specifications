"""add mapping_processing value to tp_upload_status enum

Revision ID: b6f7a8c9d0e1
Revises: a5e6f7b8c9d0
Create Date: 2026-10-06 15:00:00.000000

Задача 3.1: LLM-предсказание маппинга вынесено из HTTP-запроса в Celery-таску
`pricelist.predict_mapping`. На время анализа загрузка переводится в
промежуточный статус `mapping_processing`, поэтому в enum требуется новое значение.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6f7a8c9d0e1"
down_revision: str | Sequence[str] | None = "a5e6f7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет значение mapping_processing в тип статуса загрузки."""
    # ALTER TYPE ... ADD VALUE нельзя смешивать с использованием нового значения
    # в той же транзакции — выполняем в autocommit-блоке.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tp_upload_status ADD VALUE IF NOT EXISTS 'mapping_processing'")


def downgrade() -> None:
    """Откат не выполняется: значения enum могут использоваться в данных.

    PostgreSQL не поддерживает удаление отдельных значений enum без пересоздания
    типа, а строки со статусом mapping_processing к моменту отката могут уже
    существовать. Оставляем значение как безвредное.
    """
