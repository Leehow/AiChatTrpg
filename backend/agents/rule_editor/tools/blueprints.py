"""Blueprint tools for the rule editor agent.

Three tools:
  - `list_blueprints` returns blueprint summaries (id, name, keywords,
    taxonomy defaults, slot count). The full per-blueprint detail is
    available through `apply_blueprint`.
  - `recommend_blueprints` runs the deterministic scorer against the
    user's brief / taxonomy and returns the top-N candidates.
  - `apply_blueprint` writes the chosen blueprint into design_state
    via the service helper, persisting validation_report + design_phase
    and writing a `RulesetDraftEdit` audit row. parsed_v6 is never
    touched.
"""

from __future__ import annotations

from typing import Any

from agents.rule_editor.blueprints import (
    BlueprintNotFoundError,
    list_blueprints as _list_blueprints,
    recommend_blueprints as _recommend_blueprints,
)
from services.ruleset_draft_design import apply_blueprint_to_draft

from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)
from .design_state import _result_payload


def _blueprint_summary(bp: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": bp.get("id", ""),
        "name": bp.get("name", ""),
        "description": bp.get("description", ""),
        "keywords": list(bp.get("keywords") or []),
        "taxonomy": dict(bp.get("taxonomy") or {}),
        "slots_required_count": len(bp.get("slots_required") or []),
    }


# ---------------------------------------------------------------------------
# list_blueprints
# ---------------------------------------------------------------------------


async def _list(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    blueprints = _list_blueprints()
    return ToolResult({
        "ok": True,
        "blueprints": [_blueprint_summary(bp) for bp in blueprints],
        "total": len(blueprints),
    })


list_blueprints_tool = FunctionTool(
    name="list_blueprints",
    description=(
        "Return summaries of every built-in blueprint (id, name, "
        "keywords, taxonomy defaults, required-slot count). Use "
        "before `recommend_blueprints` if you want the full menu, "
        "or after a recommendation to inspect alternatives."
    ),
    json_schema=make_object_schema({}),
    is_write=False,
    executor=_list,
)


# ---------------------------------------------------------------------------
# recommend_blueprints
# ---------------------------------------------------------------------------


async def _recommend(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "")
    taxonomy_raw = args.get("taxonomy") or {}
    if not isinstance(taxonomy_raw, dict):
        raise ToolError("bad_arg", "taxonomy must be an object if provided")
    taxonomy = {
        str(k): str(v)
        for k, v in taxonomy_raw.items()
        if isinstance(v, str)
    }
    limit_raw = args.get("limit", 3)
    try:
        limit = max(1, min(int(limit_raw), 10))
    except (TypeError, ValueError):
        limit = 3
    candidates = _recommend_blueprints(text=text, taxonomy=taxonomy, limit=limit)
    return ToolResult({
        "ok": True,
        "candidates": [_blueprint_summary(bp) for bp in candidates],
        "total": len(candidates),
    })


recommend_blueprints_tool = FunctionTool(
    name="recommend_blueprints",
    description=(
        "Score the built-in blueprint catalog against the current "
        "brief text + taxonomy and return the top-N candidates. "
        "Deterministic scorer: keyword hits + taxonomy matches. "
        "Use to pick a starting blueprint for a vague brief; you can "
        "always switch later via another `apply_blueprint`."
    ),
    json_schema=make_object_schema({
        "text": {
            "type": "string",
            "description": "Free-text brief or pitch (optional).",
        },
        "taxonomy": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": (
                "Partial taxonomy hints (genre, tone, complexity, "
                "era, setting_type). Optional."
            ),
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    }),
    is_write=False,
    executor=_recommend,
)


# ---------------------------------------------------------------------------
# apply_blueprint
# ---------------------------------------------------------------------------


async def _apply(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    blueprint_id = str(args.get("blueprint_id") or "").strip()
    if not blueprint_id:
        raise ToolError("missing_arg", "blueprint_id required")
    try:
        result = await apply_blueprint_to_draft(
            ctx.db,
            draft_id=ctx.draft_id,
            owner_id=ctx.owner_id,
            blueprint_id=blueprint_id,
            message_id=ctx.assistant_message_id,
        )
    except BlueprintNotFoundError as e:
        raise ToolError("blueprint_not_found", str(e)) from e
    payload = _result_payload(result, write=True)
    payload["blueprint_id"] = blueprint_id
    payload["sections_seeded"] = list(result.sections_seeded)
    return ToolResult(payload, edit_id=result.edit_id)


apply_blueprint_tool = FunctionTool(
    name="apply_blueprint",
    description=(
        "Apply a built-in blueprint to design_state. Sets the "
        "blueprint reference, seeds taxonomy defaults (only for "
        "fields that are still empty), and seeds default core_loop / "
        "resolution_model / character_model when those sections are "
        "empty. Already-filled sections are preserved. Persists the "
        "updated validation_report + design_phase. parsed_v6 is "
        "never mutated by this tool. Returns the same shape as "
        "`apply_design_ops` so the agent can react to the new "
        "validation report immediately."
    ),
    json_schema=make_object_schema({
        "blueprint_id": {"type": "string"},
    }, ["blueprint_id"]),
    is_write=True,
    executor=_apply,
)


BLUEPRINT_TOOLS: list[FunctionTool] = [
    list_blueprints_tool,
    recommend_blueprints_tool,
    apply_blueprint_tool,
]


__all__ = ["BLUEPRINT_TOOLS"]
