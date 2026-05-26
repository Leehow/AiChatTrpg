"""Design tools for top-level fields: bootstrap, core_rules, companion."""

from __future__ import annotations

from typing import Any

from ._apply import apply_ops
from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


async def _bootstrap(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    book_title = str(args.get("book_title") or "").strip()
    world_mode = str(args.get("world_mode") or "").strip()
    output_language = str(args.get("output_language") or "").strip()
    if not book_title:
        raise ToolError("missing_arg", "book_title required")
    raw_packages = args.get("planned_packages") or []
    raw_families = args.get("planned_families") or []
    plan_sheet = bool(args.get("plan_character_sheet", True))

    ops: list[dict[str, Any]] = [
        {"op": "set_meta", "field": "book_title", "value": book_title},
    ]
    if world_mode:
        ops.append({"op": "set_meta", "field": "world_mode", "value": world_mode})
    if output_language:
        ops.append({
            "op": "set_meta", "field": "output_language", "value": output_language,
        })

    # Seed a core_rules placeholder so the left preview shows the row
    # immediately and the user can promote without first being blocked
    # by the empty-core-rules guard. The agent is expected to overwrite
    # this with real content via design_core_rules.
    ops.append({
        "op": "set_core_rules",
        "content": (
            f"# {book_title}\n\n"
            "(placeholder — call design_core_rules to write the real "
            "core rules text)\n"
        ),
    })

    # Seed a companion (setting / style guide) placeholder so the
    # 背景/风格 row is visible from the start. The agent uses
    # set_companion to overwrite with real content.
    ops.append({
        "op": "set_companion",
        "filename": "world_guide.md",
        "content": (
            f"# {book_title} — 风格与设定\n\n"
            "(placeholder — call set_companion to write the world / "
            "style guide)\n"
        ),
    })

    for pkg_id in raw_packages:
        pkg_id = str(pkg_id).strip()
        if not pkg_id:
            continue
        ops.append({
            "op": "upsert_rule_package",
            "id": pkg_id,
            "package": {
                "content": "(placeholder — to be filled by design_scenario)",
            },
        })
    for fam_id in raw_families:
        fam_id = str(fam_id).strip()
        if not fam_id:
            continue
        ops.append({
            "op": "upsert_parameter_family",
            "id": fam_id,
            "family": {"content": "", "json": {"entries": []}},
        })
    if plan_sheet:
        ops.append({
            "op": "set_character_sheet",
            "template_json": {
                "identity": {}, "attributes": {}, "skills": [],
            },
            "guide_content": (
                "(placeholder — to be filled by design_character_sheet)"
            ),
        })

    return await apply_ops(ctx, ops, extra_payload={
        "summary": (
            f"created framework for `{book_title}` with "
            f"{len(raw_packages)} packages and {len(raw_families)} families"
        ),
    })


bootstrap_tool = FunctionTool(
    name="bootstrap_framework",
    description=(
        "Initial design pass: sets book_title / world_mode / "
        "output_language and creates EMPTY placeholders for each "
        "planned package and family. Use this on a fresh draft so the "
        "user immediately sees structure. Don't fill content here — "
        "call design_scenario / design_parameter_family / "
        "design_character_sheet afterwards. planned_packages and "
        "planned_families should use canonical paradigm ids when "
        "possible."
    ),
    json_schema=make_object_schema({
        "book_title": {"type": "string"},
        "world_mode": {"type": "string"},
        "output_language": {"type": "string", "description": "e.g. en, zh"},
        "planned_packages": {"type": "array", "items": {"type": "string"}},
        "planned_families": {"type": "array", "items": {"type": "string"}},
        "plan_character_sheet": {"type": "boolean"},
    }, ["book_title"]),
    is_write=True,
    executor=_bootstrap,
)


async def _design_core_rules(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    content = str(args.get("content") or "")
    if not content.strip():
        raise ToolError("empty_content", "content cannot be empty")
    return await apply_ops(ctx, [{"op": "set_core_rules", "content": content}])


design_core_rules_tool = FunctionTool(
    name="design_core_rules",
    description=(
        "Write or completely rewrite the `core_rules` markdown — the "
        "foundational rules everyone needs to know. For local edits "
        "use patch_core_rules instead."
    ),
    json_schema=make_object_schema({
        "content": {"type": "string"},
    }, ["content"]),
    is_write=True,
    executor=_design_core_rules,
)


async def _patch_core_rules(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    find = str(args.get("find") or "")
    replace = str(args.get("replace") or "")
    if not find:
        raise ToolError("empty_find", "find cannot be empty")
    return await apply_ops(ctx, [{
        "op": "patch_core_rules", "find": find, "replace": replace,
    }])


patch_core_rules_tool = FunctionTool(
    name="patch_core_rules",
    description=(
        "Find/replace inside core_rules. `find` must occur EXACTLY ONCE. "
        "Use for surgical edits without rewriting the whole document."
    ),
    json_schema=make_object_schema({
        "find": {"type": "string"},
        "replace": {"type": "string"},
    }, ["find", "replace"]),
    is_write=True,
    executor=_patch_core_rules,
)


async def _set_companion(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    filename = str(args.get("filename") or "world_guide.md")
    content = str(args.get("content") or "")
    return await apply_ops(ctx, [{
        "op": "set_companion", "filename": filename, "content": content,
    }])


set_companion_tool = FunctionTool(
    name="set_companion",
    description=(
        "Write the companion file (worldview / style guide markdown). "
        "Filename is typically `world_guide.md` or `style_guide.md`."
    ),
    json_schema=make_object_schema({
        "filename": {"type": "string"},
        "content": {"type": "string"},
    }, ["content"]),
    is_write=True,
    executor=_set_companion,
)


META_DESIGN_TOOLS: list[FunctionTool] = [
    bootstrap_tool,
    design_core_rules_tool,
    patch_core_rules_tool,
    set_companion_tool,
]
