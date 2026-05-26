"""ruleset_drafts.design_state / design_phase / validation_report

Adds the design-state-first authoring fields used by the rule-design-agent
epic (P0.1). Existing drafts keep `parsed_v6` untouched and pick up safe
defaults via server_default (`{}` JSON, `'intake'` phase).

Revision ID: 006_ruleset_drafts_design_state
Revises: 005_ruleset_drafts
Create Date: 2026-05-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "006_ruleset_drafts_design_state"
down_revision = "005_ruleset_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ruleset_drafts" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("ruleset_drafts")}

    if "design_state" not in existing:
        # JSON server_default `'{}'` so legacy rows materialize as an empty
        # design state instead of NULL -- keeps the reducer/validator path
        # free of None checks.
        op.add_column(
            "ruleset_drafts",
            sa.Column(
                "design_state",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )

    if "design_phase" not in existing:
        op.add_column(
            "ruleset_drafts",
            sa.Column(
                "design_phase",
                sa.String(length=64),
                nullable=False,
                server_default="intake",
            ),
        )

    if "validation_report" not in existing:
        op.add_column(
            "ruleset_drafts",
            sa.Column(
                "validation_report",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ruleset_drafts" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("ruleset_drafts")}

    if "validation_report" in existing:
        op.drop_column("ruleset_drafts", "validation_report")
    if "design_phase" in existing:
        op.drop_column("ruleset_drafts", "design_phase")
    if "design_state" in existing:
        op.drop_column("ruleset_drafts", "design_state")
