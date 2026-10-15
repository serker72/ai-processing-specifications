"""create specification_row_candidates table

Revision ID: d3e4f5a6b7c8
Revises: c8d9e0f1a2b3
Create Date: 2026-10-14 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "specification_row_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор кандидата",
        ),
        sa.Column(
            "specification_row_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор строки спецификации",
        ),
        sa.Column(
            "catalog_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Идентификатор позиции каталога",
        ),
        sa.Column("rank", sa.Integer(), nullable=False, comment="Позиция кандидата в топе (1-based)"),
        sa.Column("score", sa.Float(), nullable=False, comment="Косинусная схожесть (0.0–1.0)"),
        sa.Column("match_tier", sa.String(20), nullable=False, comment="Тип матчинга: auto / top_n"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specification_row_candidates")),
        comment="Кандидаты из векторного поиска для строк спецификации",
    )

    op.create_foreign_key(
        op.f("fk_specification_row_candidates_specification_row_id_specification_rows"),
        "specification_row_candidates",
        "specification_rows",
        ["specification_row_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        op.f("fk_specification_row_candidates_catalog_item_id_catalog_items"),
        "specification_row_candidates",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
    )

    op.create_index(
        op.f("ix_specification_row_candidates_specification_row_id"),
        "specification_row_candidates",
        ["specification_row_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_specification_row_candidates_specification_row_id"), table_name="specification_row_candidates")
    op.drop_constraint(
        op.f("fk_specification_row_candidates_catalog_item_id_catalog_items"),
        "specification_row_candidates",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_specification_row_candidates_specification_row_id_specification_rows"),
        "specification_row_candidates",
        type_="foreignkey",
    )
    op.drop_table("specification_row_candidates")
