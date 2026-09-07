"""create table specification_rows

Revision ID: 2aa8ca5bea0a
Revises: 81a67f2555e4
Create Date: 2026-09-06 17:05:46.054860

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.models import MatchType, RowStatus

# revision identifiers, used by Alembic.
revision: str = "2aa8ca5bea0a"
down_revision: str | Sequence[str] | None = "81a67f2555e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "specification_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор строки"),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор сессии загрузки спецификации",
        ),
        sa.Column("row_number", sa.Integer(), nullable=False, comment="Порядковый номер строки в файле"),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False, comment="Исходные данные строки из файла"),
        sa.Column(
            "matched_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Идентификатор сопоставленной позиции каталога",
        ),
        sa.Column(
            "match_type",
            sa.Enum(MatchType, name="tp_match_type"),
            nullable=True,
            comment="Тип результата матчинга (Tier 1/2/3)",
        ),
        sa.Column(
            "status",
            sa.Enum(RowStatus, name="tp_row_status"),
            nullable=False,
            comment="Статус строки",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specification_rows")),
        comment="Строки спецификаций клиентов с результатами матчинга",
    )

    op.create_foreign_key(
        op.f("fk_specification_rows_upload_id_specification_uploads"),
        "specification_rows",
        "specification_uploads",
        ["upload_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        op.f("fk_specification_rows_matched_item_id_catalog_items"),
        "specification_rows",
        "catalog_items",
        ["matched_item_id"],
        ["id"],
    )

    op.create_index(
        op.f("ix_specification_rows_upload_id"),
        "specification_rows",
        ["upload_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_specification_rows_upload_id"), table_name="specification_rows")
    op.drop_table("specification_rows")
    op.execute("DROP TYPE IF EXISTS tp_match_type")
    op.execute("DROP TYPE IF EXISTS tp_row_status")
