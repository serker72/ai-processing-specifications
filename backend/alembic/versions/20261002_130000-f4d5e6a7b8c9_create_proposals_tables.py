"""create proposals, proposal_documents, proposal_counters

Revision ID: f4d5e6a7b8c9
Revises: e3c4d5f6a7b8
Create Date: 2026-10-02 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4d5e6a7b8c9"
down_revision: str | Sequence[str] | None = "e3c4d5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт таблицы КП, версий файлов и счётчика номеров."""
    op.create_table(
        "proposal_counters",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_number", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_proposal_counters")),
        comment="Счётчики номеров коммерческих предложений по годам",
    )

    op.create_table(
        "proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_proposals_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_proposals_client_id_clients")
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["specification_uploads.id"],
            name=op.f("fk_proposals_upload_id_specification_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
        sa.UniqueConstraint("number", name=op.f("uq_proposals_number")),
        comment="Коммерческие предложения",
    )
    op.create_index(op.f("ix_proposals_upload_id"), "proposals", ["upload_id"])

    op.create_table(
        "proposal_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("format", sa.String(8), server_default=sa.text("'pdf'"), nullable=False),
        sa.Column("rows_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_proposal_documents_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_documents")),
        comment="Файлы (версии) коммерческих предложений",
    )
    op.create_index(
        op.f("ix_proposal_documents_proposal_id"), "proposal_documents", ["proposal_id"]
    )


def downgrade() -> None:
    """Удаляет таблицы КП, версий файлов и счётчика номеров."""
    op.drop_index(op.f("ix_proposal_documents_proposal_id"), table_name="proposal_documents")
    op.drop_table("proposal_documents")
    op.drop_index(op.f("ix_proposals_upload_id"), table_name="proposals")
    op.drop_table("proposals")
    op.drop_table("proposal_counters")
