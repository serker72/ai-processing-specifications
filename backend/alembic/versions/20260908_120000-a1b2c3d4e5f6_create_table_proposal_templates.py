"""Create table proposal_templates

Revision ID: 20260908_120000-a1b2c3d4e5f6
Revises: 20260906_170550-a6fd053f3c77
Create Date: 2026-09-08 12:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "a6fd053f3c77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт таблицу proposal_templates."""
    op.create_table(
        "proposal_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("html_key", sa.Text(), nullable=False),
        sa.Column("start_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_templates")),
        sa.UniqueConstraint("start_date", name=op.f("uq_proposal_templates_start_date")),
        comment="Шаблоны коммерческих предложений",
    )


def downgrade() -> None:
    """Удаляет таблицу proposal_templates."""
    op.drop_table("proposal_templates")
