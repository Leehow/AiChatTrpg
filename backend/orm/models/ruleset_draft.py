"""ORM models for the conversational rule editor.

A `RulesetDraft` holds an in-progress V6 artifact plus pointers to its
origin: `base_ruleset_id` (fork source, informational only) and/or
`target_ruleset_id` (in-place edit target -- apply_patch cascades to this
ruleset and bumps its updated_at so running sessions pick up the change).

`RulesetDraftMessage` is the agent transcript (user / assistant / tool) in
OpenAI Chat Completions message shape. `RulesetDraftEdit` records each
applied patch batch with before/after diff, supporting linear undo and
audit.

See: docs/design/2026-05-01-rule-editor-agent.md
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, utcnow


class RulesetDraft(Base, TimestampMixin):
    __tablename__ = "ruleset_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    parsed_v6: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict,
    )

    # Fork source -- informational only, not enforced as FK so deleting the
    # source ruleset does not cascade-delete the draft.
    base_ruleset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # In-place edit target -- apply_patch cascades to this ruleset.
    target_ruleset_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )

    needs_dice_compile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    needs_character_ui_compile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # Design-state-first authoring artifact (P0.1). The agent loop reads
    # and writes `design_state`; only `compile_design_state_to_parsed_v6`
    # produces runtime `parsed_v6`. See docs/epics/rule_design_agent/.
    design_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict,
    )
    design_phase: Mapped[str] = mapped_column(
        String(64), nullable=False, default="intake", server_default="intake",
    )
    validation_report: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict,
    )


class RulesetDraftMessage(Base):
    """Agent transcript entry. `seq` is monotonic per draft for paginated reads."""

    __tablename__ = "ruleset_draft_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ruleset_drafts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # "user" | "assistant" | "tool"
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Which agent transcript this row belongs to: "main" (rule editor)
    # or "dice" (dice procedure designer). Each pane reads only its own
    # kind so the two transcripts stay independent.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="main", server_default="main",
    )
    # OpenAI Chat Completions message dict: text, tool_calls, tool_call_id, etc.
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )


class RulesetDraftEdit(Base):
    """One applied patch batch. `diff` enables undo; `undone` flags revoked edits."""

    __tablename__ = "ruleset_draft_edits"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ruleset_drafts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Which assistant turn (RulesetDraftMessage.id) produced this batch.
    # Nullable because user-initiated undo also writes edits without a
    # message context.
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    ops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    undone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
