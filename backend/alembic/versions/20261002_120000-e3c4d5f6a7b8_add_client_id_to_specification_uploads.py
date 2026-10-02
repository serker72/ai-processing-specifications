"""add client_id to specification_uploads

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-10-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e3c4d5f6a7b8"
down_revision: str | Sequence[str] | None = "d2b3c4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет обязательного клиента к загрузкам спецификаций.

    Существующие загрузки — smoke-данные без клиента, поэтому сначала они
    удаляются (строки уходят каскадом по FK specification_rows.upload_id),
    затем добавляется NOT NULL-колонка client_id.
    """
    op.execute("DELETE FROM specification_uploads")
    op.add_column(
        "specification_uploads",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_specification_uploads_client_id_clients"),
        "specification_uploads",
        "clients",
        ["client_id"],
        ["id"],
    )


def downgrade() -> None:
    """Удаляет связь с клиентом у загрузок спецификаций."""
    op.drop_constraint(
        op.f("fk_specification_uploads_client_id_clients"),
        "specification_uploads",
        type_="foreignkey",
    )
    op.drop_column("specification_uploads", "client_id")
