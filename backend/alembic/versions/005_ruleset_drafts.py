"""ruleset_drafts + messages + edits for the conversational rule editor

Revision ID: 005_ruleset_drafts
Revises: 004_rulesets_is_shared
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "005_ruleset_drafts"
down_revision = "004_rulesets_is_shared"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "ruleset_drafts" not in existing_tables:
        op.create_table(
            "ruleset_drafts",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("parsed_v6", sa.JSON(), nullable=False),
            sa.Column("base_ruleset_id", sa.String(length=64), nullable=True),
            sa.Column("target_ruleset_id", sa.String(length=64), nullable=True),
            sa.Column(
                "needs_dice_compile", sa.Boolean(),
                nullable=False, server_default=sa.text("false"),
            ),
            sa.Column(
                "needs_character_ui_compile", sa.Boolean(),
                nullable=False, server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_ruleset_drafts_owner_id", "ruleset_drafts", ["owner_id"],
        )
        op.create_index(
            "ix_ruleset_drafts_target_ruleset_id", "ruleset_drafts",
            ["target_ruleset_id"],
        )

    if "ruleset_draft_messages" not in existing_tables:
        op.create_table(
            "ruleset_draft_messages",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "draft_id", sa.String(length=64),
                sa.ForeignKey("ruleset_drafts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_ruleset_draft_messages_draft_id_seq",
            "ruleset_draft_messages", ["draft_id", "seq"],
        )

    if "ruleset_draft_edits" not in existing_tables:
        op.create_table(
            "ruleset_draft_edits",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "draft_id", sa.String(length=64),
                sa.ForeignKey("ruleset_drafts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("message_id", sa.String(length=64), nullable=True),
            sa.Column("ops", sa.JSON(), nullable=False),
            sa.Column("diff", sa.JSON(), nullable=False),
            sa.Column(
                "undone", sa.Boolean(),
                nullable=False, server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_ruleset_draft_edits_draft_id",
            "ruleset_draft_edits", ["draft_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "ruleset_draft_edits" in existing_tables:
        op.drop_index("ix_ruleset_draft_edits_draft_id", table_name="ruleset_draft_edits", if_exists=True)
        op.drop_table("ruleset_draft_edits")
    if "ruleset_draft_messages" in existing_tables:
        op.drop_index("ix_ruleset_draft_messages_draft_id_seq", table_name="ruleset_draft_messages", if_exists=True)
        op.drop_table("ruleset_draft_messages")
    if "ruleset_drafts" in existing_tables:
        op.drop_index("ix_ruleset_drafts_target_ruleset_id", table_name="ruleset_drafts", if_exists=True)
        op.drop_index("ix_ruleset_drafts_owner_id", table_name="ruleset_drafts", if_exists=True)
        op.drop_table("ruleset_drafts")
