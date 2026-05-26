"""Read-only dice tools: respond + read_dice_state."""

from __future__ import annotations

from typing import Any

from agents.rule_editor.tools.base import (
    FunctionTool,
    ToolContext,
    ToolResult,
    make_object_schema,
)
from services import ruleset_drafts as svc


async def _respond(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return ToolResult({"ok": True})


respond_tool = FunctionTool(
    name="respond",
    description=(
        "Use when the user asks a discussion question — no compile, no "
        "test. Speak to the user via your normal assistant text."
    ),
    json_schema=make_object_schema({"text": {"type": "string"}}, ["text"]),
    is_write=False,
    executor=_respond,
)


async def _read_dice_state(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    parsed = draft.parsed_v6 or {}
    dice_ir = parsed.get("dice_ir") or {}
    package = dice_ir.get("package") or {}
    compiled = package.get("compiled") or {}
    procedures = compiled.get("check_specs") or []
    out_procs: list[dict[str, Any]] = []
    for p in procedures:
        if not isinstance(p, dict):
            continue
        spec = p.get("check_spec") or {}
        out_procs.append({
            "procedure_id": p.get("procedure_id", ""),
            "name": p.get("name", ""),
            "engine": spec.get("engine", ""),
            "primary_family": p.get("primary_family", ""),
            "validation_ok": (p.get("validation") or {}).get("ok"),
            "samples_count": len(
                (p.get("validation") or {}).get("samples") or []
            ),
        })
    return ToolResult({
        "default_procedure_id": compiled.get("default_procedure_id", ""),
        "overall_ok": compiled.get("overall_ok"),
        "model": dice_ir.get("model", ""),
        "saved_at": dice_ir.get("saved_at", ""),
        "procedures": out_procs,
    })


read_dice_state_tool = FunctionTool(
    name="read_dice_state",
    description=(
        "Read the current draft's compiled dice procedures: ids, "
        "engines, validation status. Use BEFORE designing to know what "
        "already exists and avoid duplicating."
    ),
    json_schema=make_object_schema({}),
    is_write=False,
    executor=_read_dice_state,
)
