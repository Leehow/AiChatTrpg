"""Pydantic IO schemas for the conversational rule editor."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateDraftRequest(BaseModel):
    base_ruleset_id: str | None = Field(
        default=None,
        description="If set, copy parsed_v6 from this ruleset (fork).",
    )
    target_ruleset_id: str | None = Field(
        default=None,
        description=(
            "If set, draft is bound to this ruleset; apply_patch cascades "
            "to it. Caller must own the target."
        ),
    )
    title: str | None = Field(
        default=None,
        description="Optional display title; defaults to source title or '未命名草稿'.",
    )


class DraftSummary(BaseModel):
    id: str
    owner_id: str
    title: str
    base_ruleset_id: str | None = None
    target_ruleset_id: str | None = None
    needs_dice_compile: bool
    needs_character_ui_compile: bool
    # Design-state-first authoring fields (P0.1). `design_phase` is small
    # enough to ship in list views so the UI can render phase badges
    # without a second roundtrip; the heavier `design_state` and
    # `validation_report` blobs live on DraftDetail.
    design_phase: str = "intake"
    created_at: datetime
    updated_at: datetime


class DraftMessage(BaseModel):
    id: str
    seq: int
    role: Literal["user", "assistant", "tool"]
    content: dict[str, Any]
    created_at: datetime


class DraftEdit(BaseModel):
    id: str
    message_id: str | None = None
    ops: list[dict[str, Any]]
    diff: list[dict[str, Any]]
    undone: bool
    created_at: datetime


class DraftDetail(DraftSummary):
    parsed_v6: dict[str, Any]
    # Design-state-first authoring artifact and latest validator output.
    # Empty defaults keep legacy drafts loadable without a destructive
    # migration; populated by P0.2+ reducer/validator.
    design_state: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    messages: list[DraftMessage] = Field(default_factory=list)
    edits: list[DraftEdit] = Field(default_factory=list)


class ApplyPatchRequest(BaseModel):
    """Direct API for applying patch ops without going through the agent.

    The frontend may call this for manual undo/redo or for internal tools.
    The agent itself goes through `POST /{id}/messages` (P3).
    """
    ops: list[dict[str, Any]]


class ApplyPatchResponse(BaseModel):
    edit_id: str
    diff: list[dict[str, Any]]
    needs_dice_compile: bool
    needs_character_ui_compile: bool
    parsed_v6_after: dict[str, Any]


class UndoEditResponse(BaseModel):
    new_edit_id: str
    parsed_v6_after: dict[str, Any]


class PromoteRequest(BaseModel):
    mode: Literal["new", "target"] = Field(
        ..., description="`new` = create a new ruleset; `target` = overwrite the bound target.",
    )
    new_title: str | None = Field(
        default=None,
        description="Required when mode='new'; ignored otherwise.",
    )


class PromoteResponse(BaseModel):
    ruleset_id: str
    mode: Literal["new", "target"]


class RecompileResponse(BaseModel):
    ok: bool
    parsed_v6_after: dict[str, Any]


class CompileDesignResponse(BaseModel):
    """Result of POST /api/ruleset-drafts/{id}/compile-design.

    `status='success'` means parsed_v6 was updated and an edit row was
    written. `status='blocked'` means the validator surfaced blocking
    issues; parsed_v6 is unchanged. `validation_report` always carries
    the report from the validator pass that produced this response.
    """
    status: Literal["success", "blocked"]
    edit_id: str | None = None
    parsed_v6_after: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    sections_emitted: list[str] = Field(default_factory=list)
    ready_blockers: list[str] = Field(default_factory=list)
    needs_dice_compile: bool = False
    needs_character_ui_compile: bool = False
    design_phase: str = "intake"
    error: str | None = None
