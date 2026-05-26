"""invite codes for hosted registration

Revision ID: 007_invite_codes
Revises: 006_ruleset_drafts_design_state
Create Date: 2026-05-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "007_invite_codes"
down_revision = "006_ruleset_drafts_design_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "invite_codes" in inspector.get_table_names():
        return

    op.create_table(
        "invite_codes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invite_codes_code_hash",
        "invite_codes",
        ["code_hash"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "invite_codes" not in inspector.get_table_names():
        return

    op.drop_index("ix_invite_codes_code_hash", table_name="invite_codes")
    op.drop_table("invite_codes")
