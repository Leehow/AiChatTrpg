"""authoritative memory runtime v3

Revision ID: 003_authoritative_memory_runtime_v3
Revises:
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003_authoritative_memory_runtime_v3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trpg_memory_items" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("trpg_memory_items")}
    if "source_quotes_json" not in existing:
        op.add_column("trpg_memory_items", sa.Column("source_quotes_json", sa.JSON(), nullable=False, server_default="[]"))
    if "identity_scope" not in existing:
        op.add_column("trpg_memory_items", sa.Column("identity_scope", sa.String(length=40), nullable=False, server_default="durable_fact"))
    if "reinforcement_count" not in existing:
        op.add_column("trpg_memory_items", sa.Column("reinforcement_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(
        "ix_trpg_memory_items_identity_scope",
        "trpg_memory_items",
        ["session_id", "identity_scope", "status"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trpg_memory_items" not in inspector.get_table_names():
        return
    op.drop_index("ix_trpg_memory_items_identity_scope", table_name="trpg_memory_items", if_exists=True)
    existing = {col["name"] for col in inspector.get_columns("trpg_memory_items")}
    for name in ("reinforcement_count", "identity_scope", "source_quotes_json"):
        if name in existing:
            op.drop_column("trpg_memory_items", name)
