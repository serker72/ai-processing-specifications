"""add content_hash column to catalog_items

Revision ID: e7f8a9b0c1d2
Revises: b6f7a8c9d0e1
Create Date: 2026-10-09 10:00:00.000000

Задача 3: Неоптимальная векторизация каталога — эмбеддинги пересчитываются
для всех строк при каждой загрузке прайс-листа.

Решение: добавить колонку content_hash (SHA-256 от sku + name); при
векторизации пропускать строки с неизменившимся хэшем, пересчитывая
эмбеддинг только для новых/изменённых позиций.
"""

import hashlib
from collections.abc import Iterator

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "b6f7a8c9d0e1"
branch_labels: str | None = None
depends_on: str | None = None


def _content_hash(sku: str, name: str) -> str:
    """SHA-256 хэш содержимого (sku + name) — совпадает с ``content_hash_of``
    из репозитория каталога.
    """
    return hashlib.sha256(f"{sku}\n{name}".encode()).hexdigest()


def _batched(iterable: list, size: int) -> Iterator[list]:
    """Разбить список на батчи заданного размера."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def upgrade() -> None:
    """Добавляет колонку content_hash и заполняет хэши для существующих записей."""
    # 1. Добавить колонку
    op.add_column(
        "catalog_items",
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 хэш содержимого (sku + name) для пропуска неизменных строк",
        ),
    )

    # 2. Вычислить хэши для всех существующих записей батчами
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, sku, name FROM catalog_items WHERE content_hash IS NULL")
    ).fetchall()
    if not rows:
        return

    pairs = [(row.id, _content_hash(str(row.sku), str(row.name))) for row in rows]
    for batch in _batched(pairs, 500):
        params = {}
        for i, (item_id, h) in enumerate(batch):
            params[f"id_{i}"] = str(item_id)
            params[f"hash_{i}"] = h
        values_sql = ", ".join(
            f"(CAST(:id_{i} AS uuid), :hash_{i})" for i in range(len(batch))
        )
        conn.execute(
            sa.text(
                "UPDATE catalog_items SET content_hash = v.hash "
                "FROM (VALUES " + values_sql + ") AS v(id, hash) "
                "WHERE catalog_items.id = v.id"
            ),
            params,
        )


def downgrade() -> None:
    """Удалить колонку content_hash."""
    op.drop_column("catalog_items", "content_hash")
