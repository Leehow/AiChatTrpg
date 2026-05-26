"""Inspect tools: `respond` (no-op acknowledgement) + `read_draft`."""

from __future__ import annotations

from typing import Any

from services import ruleset_drafts as svc

from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


async def _respond(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "")
    return ToolResult({"ok": True, "echoed": text[:200]})


respond_tool = FunctionTool(
    name="respond",
    description=(
        "Use when the user asks a question or wants to discuss design — "
        "no edits will be made. The text passed here is logged but not "
        "shown to the user; speak to the user via your normal assistant "
        "message text."
    ),
    json_schema=make_object_schema(
        {"text": {"type": "string"}}, ["text"],
    ),
    is_write=False,
    executor=_respond,
)


async def _read_draft(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    section = str(args.get("section") or "").strip()
    parsed = draft.parsed_v6 or {}

    if not section or section == "all":
        return ToolResult({
            "title": draft.title,
            "base_ruleset_id": draft.base_ruleset_id,
            "target_ruleset_id": draft.target_ruleset_id,
            "needs_dice_compile": bool(draft.needs_dice_compile),
            "needs_character_ui_compile": bool(draft.needs_character_ui_compile),
            "meta": {
                "book_id": parsed.get("book_id", ""),
                "book_title": parsed.get("book_title", ""),
                "world_mode": parsed.get("world_mode", ""),
                "output_language": parsed.get("output_language", ""),
            },
            "core_rules_chars": len(str(parsed.get("core_rules") or "")),
            "scenarios": [
                p.get("package_id", "")
                for p in (parsed.get("rule_packages") or [])
                if isinstance(p, dict)
            ],
            "parameter_families": [
                f.get("family_id", "")
                for f in (parsed.get("parameter_families") or [])
                if isinstance(f, dict)
            ],
            "has_character_sheet": bool(
                parsed.get("character_sheet")
                and parsed["character_sheet"].get("template_json"),
            ),
        })

    if section == "core":
        return ToolResult({
            "core_rules": parsed.get("core_rules", ""),
            "companion": parsed.get("companion", {}),
        })
    if section == "scenarios":
        return ToolResult({"scenarios": parsed.get("rule_packages") or []})
    if section == "parameters":
        return ToolResult({"parameters": parsed.get("parameter_families") or []})
    if section == "character_sheet":
        return ToolResult({"character_sheet": parsed.get("character_sheet")})
    raise ToolError(
        "bad_section",
        f"unknown section `{section}`; one of: core, scenarios, "
        "parameters, character_sheet, all",
    )


read_draft_tool = FunctionTool(
    name="read_draft",
    description=(
        "Read the current draft state. Use BEFORE designing to see what "
        "already exists. `section` ∈ {core, scenarios, parameters, "
        "character_sheet}; omit for a summary."
    ),
    json_schema=make_object_schema({
        "section": {
            "type": "string",
            "enum": [
                "all", "core", "scenarios", "parameters", "character_sheet",
            ],
        },
    }),
    is_write=False,
    executor=_read_draft,
)


# `respond_tool` is intentionally NOT exported to the agent. The model
# was wrapping every chat reply in a `respond(text=...)` call, which
# made discussion turns render as tool-call cards instead of chat
# bubbles. With it removed, the LLM falls through to plain assistant
# text — exactly what real users expect for a "discuss before
# editing" turn.
INSPECT_TOOLS: list[FunctionTool] = [read_draft_tool]
