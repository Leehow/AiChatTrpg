"""Design tools for character_sheet + character_ui compile."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from agents.rule_editor.paradigms import CHARACTER_SHEET_PARADIGM
from services import ruleset_drafts as svc

from ._apply import apply_ops
from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


async def _design_character_sheet(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    template_json = args.get("template_json")
    guide_content = args.get("guide_content")
    if template_json is None or not isinstance(template_json, dict):
        raise ToolError("missing_arg", "template_json (object) required")
    val = CHARACTER_SHEET_PARADIGM.validate(template_json, guide_content)
    if not val.ok:
        raise ToolError("validation_failed", "; ".join(val.errors))
    return await apply_ops(ctx, [{
        "op": "set_character_sheet",
        "template_json": template_json,
        "guide_content": (
            guide_content if isinstance(guide_content, str) else None
        ),
    }], extra_payload={"warnings": val.warnings})


design_sheet_tool = FunctionTool(
    name="design_character_sheet",
    description=(
        "Write or rewrite the character_sheet template + creation "
        "guide. `template_json` is the JSON skeleton (suggested top-"
        "level keys: identity, attributes, skills, equipment, etc.). "
        "CANONICAL FIELD RULES: numeric attributes must use "
        "`{\"value\": <int>}` (NEVER `default`, `base`, or `score`). "
        "Skills array entries are `{name, base, value}`. Equipment is "
        "`{weapons: [], items: []}`. List ONLY rules-acknowledged "
        "skills — the runtime will refuse to add fields not in the "
        "template, so missing entries cannot be hallucinated later. "
        "`guide_content` is markdown explaining how to create a "
        "character."
    ),
    json_schema=make_object_schema({
        "template_json": {"type": "object", "additionalProperties": True},
        "guide_content": {"type": "string"},
    }, ["template_json"]),
    is_write=True,
    executor=_design_character_sheet,
)


async def _patch_character_sheet_field(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    path = args.get("path")
    if not isinstance(path, list) or not path:
        raise ToolError("bad_path", "path must be a non-empty list")
    value = args.get("value")
    return await apply_ops(ctx, [{
        "op": "patch_character_sheet_field",
        "path": path,
        "value": value,
    }])


patch_sheet_tool = FunctionTool(
    name="patch_character_sheet_field",
    description=(
        "Surgical edit on a single field inside character_sheet. `path` "
        "is a list of keys / array indices, e.g. "
        "['template_json','attributes','STR','default']. `value` is "
        "the new value (any JSON-serializable type)."
    ),
    json_schema=make_object_schema({
        "path": {"type": "array", "items": {}},
        "value": {},
    }, ["path", "value"]),
    is_write=True,
    executor=_patch_character_sheet_field,
)


async def _compile_character_ui(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    # Reuse the route-side compile setup. Importing inside the function
    # avoids a circular import (routes -> tools registry -> here).
    from routes.rulesets import _resolve_default_compiler_config
    from agents.trpg.character_ui import (
        CharacterUICompilerError,
        compile_character_ui as _compile_ui,
    )

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    parsed_v6 = dict(draft.parsed_v6 or {})
    sheet = parsed_v6.get("character_sheet")
    if not isinstance(sheet, dict) or not isinstance(
        sheet.get("template_json"), dict,
    ):
        raise ToolError(
            "no_character_sheet_template",
            "character_sheet.template_json missing — design it first",
        )
    cfg = await _resolve_default_compiler_config(ctx.db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise ToolError(
            "no_api_config",
            "no API config available for the default compiler model",
        )
    try:
        # `compile_character_ui` returns the wrapped artifact directly.
        # Match the canonical signature: positional `parsed_v6` +
        # required `book_title` kwarg.
        artifact = await _compile_ui(
            parsed_v6,
            book_title=str(parsed_v6.get("book_title") or draft.title or ""),
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=str(parsed_v6.get("output_language") or "en"),
        )
    except CharacterUICompilerError as e:
        raise ToolError("compile_failed", str(e)) from e

    parsed_v6["character_ui"] = artifact
    draft.parsed_v6 = parsed_v6
    flag_modified(draft, "parsed_v6")
    draft.needs_character_ui_compile = False
    await ctx.db.commit()
    await ctx.db.refresh(draft)
    return ToolResult({"ok": True, "artifact_size": len(str(artifact))})


compile_ui_tool = FunctionTool(
    name="compile_character_ui",
    description=(
        "Trigger backend compilation of the character_sheet UI schema. "
        "Run after design_character_sheet so the user's create-character "
        "flow has a fresh widget tree. Synchronous — may take a few "
        "seconds."
    ),
    json_schema=make_object_schema({}),
    is_write=True,
    executor=_compile_character_ui,
)


SHEET_DESIGN_TOOLS: list[FunctionTool] = [
    design_sheet_tool,
    patch_sheet_tool,
    compile_ui_tool,
]
