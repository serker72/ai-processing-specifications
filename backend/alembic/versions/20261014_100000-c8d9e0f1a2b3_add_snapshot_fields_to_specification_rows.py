"""add snapshot fields to specification_rows

Revision ID: c8d9e0f1a2b3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-14 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Поле выбора менеджера: позиция каталога, подтверждённая вручную
    op.add_column(
        "specification_rows",
        sa.Column(
            "selected_catalog_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Позиция каталога, выбранная менеджером (для top_n/auto с ручным подтверждением)",
        ),
    )
    op.create_foreign_key(
        op.f("fk_specification_rows_selected_catalog_item_id_catalog_items"),
        "specification_rows",
        "catalog_items",
        ["selected_catalog_item_id"],
        ["id"],
    )

    # Флаг ручного выбора: отличается от автоматического
    op.add_column(
        "specification_rows",
        sa.Column(
            "is_overridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Флаг: выбор менеджера отличается от автоматического",
        ),
    )

    # Снапшоты наименования/артикула/цены/единицы на момент матчинга (для стабильного КП)
    op.add_column(
        "specification_rows",
        sa.Column("snapshot_item_name", sa.Text(), nullable=True, comment="Снапшот наименования товара на момент матчинга (для КП)"),
    )
    op.add_column(
        "specification_rows",
        sa.Column("snapshot_sku", sa.String(255), nullable=True, comment="Снапшот артикула товара на момент матчинга (для КП)"),
    )
    op.add_column(
        "specification_rows",
        sa.Column("snapshot_price", sa.Numeric(12, 2), nullable=True, comment="Снапшот цены товара на момент матчинга (для КП)"),
    )
    op.add_column(
        "specification_rows",
        sa.Column("snapshot_unit", sa.String(50), nullable=True, comment="Снапшот единицы измерения на момент матчинга (для КП)"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_specification_rows_selected_catalog_item_id_catalog_items"),
        "specification_rows",
        type_="foreignkey",
    )
    op.drop_column("specification_rows", "snapshot_unit")
    op.drop_column("specification_rows", "snapshot_price")
    op.drop_column("specification_rows", "snapshot_sku")
    op.drop_column("specification_rows", "snapshot_item_name")
    op.drop_column("specification_rows", "is_overridden")
    op.drop_column("specification_rows", "selected_catalog_item_id")
