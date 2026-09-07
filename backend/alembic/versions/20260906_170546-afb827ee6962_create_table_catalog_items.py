"""create table catalog_items

Revision ID: afb827ee6962
Revises: 98660febdf1e
Create Date: 2026-09-06 17:05:45.302058

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "afb827ee6962"
down_revision: str | Sequence[str] | None = "98660febdf1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="Идентификатор позиции каталога"),
        sa.Column("sku", sa.String(length=255), nullable=False, comment="Артикул (SKU)"),
        sa.Column("name", sa.Text(), nullable=False, comment="Наименование позиции"),
        sa.Column("unit", sa.String(length=32), nullable=True, comment="Единица измерения"),
        sa.Column("price", sa.Float(), nullable=True, comment="Цена за единицу"),
        sa.Column(
            "embedding", Vector(768), nullable=True, comment="Эмбеддинг наименования (768-dim, multilingual-e5-base)"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Время создания записи",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Время последнего обновления",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_items")),
        comment="Номенклатура каталога (из прайс-листов поставщиков)",
    )

    op.create_index(op.f("ix_catalog_items_sku"), "catalog_items", ["sku"], unique=False)

    op.create_index(op.f("uq_catalog_items_sku_name"), "catalog_items", ["sku", "name"], unique=True)

    # HNSW-индекс для векторного поиска по косинусной дистанции (<=>)
    op.create_index(
        op.f("ix_catalog_items_embedding"),
        "catalog_items",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_catalog_items_embedding"), table_name="catalog_items")
    op.drop_index(op.f("uq_catalog_items_sku_name"), table_name="catalog_items")
    op.drop_index(op.f("ix_catalog_items_sku"), table_name="catalog_items")
    op.drop_table("catalog_items")
