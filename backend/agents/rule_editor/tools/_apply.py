"""Shared helper: turn a list of patch ops into a service-layer apply."""

from __future__ import annotations

from typing import Any

from agents.rule_editor.patch_ops import PatchError
from services import ruleset_drafts as svc

from .base import ToolContext, ToolError, ToolResult


async def apply_ops(
    ctx: ToolContext,
    raw_ops: list[dict[str, Any]],
    extra_payload: dict[str, Any] | None = None,
) -> ToolResult:
    """Run a batch of patch ops through the service layer; convert
    PatchError → ToolError so the LLM gets a structured response."""
    try:
        edit = await svc.apply_ops_to_draft(
            ctx.db,
            draft_id=ctx.draft_id,
            owner_id=ctx.owner_id,
            raw_ops=raw_ops,
            message_id=ctx.assistant_message_id,
        )
    except PatchError as e:
        raise ToolError(e.code, e.message) from e
    payload: dict[str, Any] = {
        "ok": True,
        "edit_id": edit.id,
        "diff": list(edit.diff or []),
    }
    if extra_payload:
        payload.update(extra_payload)
    return ToolResult(payload, edit_id=edit.id)
