"""rulesets.is_shared visibility flag

Revision ID: 004_rulesets_is_shared
Revises: 003_authoritative_memory_runtime_v3
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "004_rulesets_is_shared"
down_revision = "003_authoritative_memory_runtime_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "rulesets" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("rulesets")}
    if "is_shared" not in existing:
        # Existing rows pre-date the flag and were owner-private by API
        # contract — keep them that way (server_default=false) so flipping
        # the schema doesn't expose anyone's library to other users.
        op.add_column(
            "rulesets",
            sa.Column(
                "is_shared",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "rulesets" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("rulesets")}
    if "is_shared" in existing:
        op.drop_column("rulesets", "is_shared")
