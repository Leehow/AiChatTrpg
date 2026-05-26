"""Design-state tools for the rule editor agent.

These tools are the **only** way the LLM is allowed to author the V6
authoring artifact in P0.6. parsed_v6 is downstream and writeable only
via the validator-gated `compile_design` tool. Legacy parsed_v6 write
tools live elsewhere in the registry but are no longer advertised by
`build_tools_schema_for_draft`.

Each write tool's payload includes the design summary, validation
report, design phase, can_compile flag, and a special marker key
`_design_state_changed=True` so the agent loop can emit a structured
SSE event without re-running the validator.
"""

from __future__ import annotations

from typing import Any

from agents.rule_editor.design_state import (
    DesignPatchError,
    build_summary,
    empty_design_state,
    validate_design_state,
)
from agents.rule_editor.design_state.defaults import (
    BRIEF_FIELDS,
    CATALOG_NAMES,
    COMPILE_STATUSES,
    PHASES,
    SLOT_STATUSES,
    TAXONOMY_FIELDS,
)
from services import ruleset_drafts as svc
from services.ruleset_draft_design import (
    DesignWriteResult,
    apply_design_ops_to_draft,
    validate_design_state_for_draft,
)

from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


# JSON schemas for each apply_design_ops branch. Field names mirror the
# pydantic op models in `agents.rule_editor.design_state.models`; the
# reducer is the source of truth and rejects bad payloads via
# `DesignPatchError`. Branches are closed (`additionalProperties: False`)
# so a wrong field name fails fast instead of being silently ignored.
_STR = {"type": "string"}
_STR_NONEMPTY = {"type": "string", "minLength": 1}
_STR_ARR = {"type": "array", "items": _STR}
_OBJ_ARR = {"type": "array", "items": {"type": "object"}}
_OP_BRANCHES: tuple[tuple[str, dict[str, Any], list[str]], ...] = (
    ("set_phase", {"phase": {"type": "string", "enum": list(PHASES)}}, ["phase"]),
    (
        "set_brief_field",
        {
            "field": {"type": "string", "enum": list(BRIEF_FIELDS)},
            "value": _STR,
        },
        ["field", "value"],
    ),
    ("add_assumption", {"assumption": _STR_NONEMPTY}, ["assumption"]),
    (
        "set_taxonomy_field",
        {
            "field": {"type": "string", "enum": list(TAXONOMY_FIELDS)},
            "value": _STR,
        },
        ["field", "value"],
    ),
    (
        "set_blueprint",
        {
            "blueprint_id": _STR_NONEMPTY,
            "slots_required": _STR_ARR,
            "taxonomy_overrides": {
                "type": "object",
                "additionalProperties": _STR,
            },
        },
        ["blueprint_id"],
    ),
    (
        "set_slot_status",
        {
            "slot": _STR_NONEMPTY,
            "status": {"type": "string", "enum": list(SLOT_STATUSES)},
        },
        ["slot", "status"],
    ),
    (
        "set_core_loop",
        {"summary": _STR, "phases": _STR_ARR, "pacing": _STR},
        [],
    ),
    (
        "set_character_model",
        {
            "archetypes": _STR_ARR,
            "attributes": {
                **_OBJ_ARR,
                "description": (
                    "Attribute objects, each with at least `id` and "
                    "`name` (e.g. {id:'str', name:'Strength'})."
                ),
            },
            "derived_stats": _OBJ_ARR,
            "progression_model": _STR,
        },
        [],
    ),
    (
        "set_resolution_model",
        {
            "mechanic": _STR,
            "dice": _STR,
            "success_thresholds": {
                **_OBJ_ARR,
                "description": (
                    "Threshold objects, each typically "
                    "{name:'regular', rule:'roll <= skill'}."
                ),
            },
            "notes": _STR,
        },
        [],
    ),
    (
        "upsert_procedure",
        {
            "id": _STR_NONEMPTY,
            "procedure": {
                "type": "object",
                "description": (
                    "Procedure body. Recommended keys: name, when, "
                    "steps (list of strings or step objects)."
                ),
            },
        },
        ["id", "procedure"],
    ),
    ("remove_procedure", {"id": _STR_NONEMPTY}, ["id"]),
    (
        "upsert_catalog_entry",
        {
            "catalog": {"type": "string", "enum": list(CATALOG_NAMES)},
            "id": _STR_NONEMPTY,
            "entry": {
                "type": "object",
                "description": (
                    "Catalog entry body. Should include at least "
                    "`name` plus `summary` or `description`."
                ),
            },
        },
        ["catalog", "id", "entry"],
    ),
    (
        "remove_catalog_entry",
        {
            "catalog": {"type": "string", "enum": list(CATALOG_NAMES)},
            "id": _STR_NONEMPTY,
        },
        ["catalog", "id"],
    ),
    (
        "set_compile_status",
        {
            "status": {"type": "string", "enum": list(COMPILE_STATUSES)},
            "error": _STR,
            "parsed_v6_ref": _STR,
        },
        ["status"],
    ),
)


def _build_apply_design_ops_schema() -> dict[str, Any]:
    branches: list[dict[str, Any]] = []
    for op_name, props, required in _OP_BRANCHES:
        branches.append({
            "type": "object",
            "properties": {"op": {"const": op_name}, **props},
            "required": ["op", *required],
            "additionalProperties": False,
        })
    items_schema = {
        "type": "object",
        "description": (
            "One design-state op. `op` selects the shape; field names "
            "match the reducer (e.g. `add_assumption` uses "
            "`assumption`, `upsert_catalog_entry` requires `catalog`, "
            "`id`, and `entry`)."
        ),
        "oneOf": branches,
    }
    return {
        "type": "object",
        "properties": {
            "ops": {
                "type": "array",
                "minItems": 1,
                "items": items_schema,
                "description": (
                    "Non-empty list of design-state ops. Each op "
                    "object must select a shape via the `op` "
                    "discriminator."
                ),
            },
        },
        "required": ["ops"],
        "additionalProperties": False,
    }


_APPLY_DESIGN_OPS_SCHEMA = _build_apply_design_ops_schema()
_OP_NAMES: list[str] = [name for name, _, _ in _OP_BRANCHES]


def _result_payload(result: DesignWriteResult, *, write: bool) -> dict[str, Any]:
    """Build the payload for both read-only and write design-state tools.

    Write tools mark `_design_state_changed=True` so the agent loop
    can mirror the change to an SSE event. Read-only tools omit that
    marker but still ship the validation report so the LLM can react
    in the same turn without an extra tool call.
    """
    payload: dict[str, Any] = {
        "ok": True,
        "design_phase": result.design_phase,
        "design_summary": result.design_summary,
        "validation_report": result.validation_report,
        "can_compile": result.can_compile,
        "edit_id": result.edit_id,
        "diff": list(result.diff or []),
    }
    if write:
        payload["_design_state_changed"] = True
    return payload


# ---------------------------------------------------------------------------
# read_design_state
# ---------------------------------------------------------------------------


async def _read_design_state(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    include_full = bool(args.get("include_full", False))
    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    # Normalize missing / invalid / empty design_state to the canonical
    # default shape so the validator does not see schema_version=None
    # (which surfaces as a `schema_version_unsupported` blocker for an
    # otherwise fresh draft). Mirrors `_ensure_design_state` in
    # services/ruleset_draft_design.py.
    raw_state = draft.design_state
    if not isinstance(raw_state, dict) or not raw_state:
        state: dict[str, Any] = empty_design_state()
    else:
        state = dict(raw_state)
    report_obj = validate_design_state(state)
    report = report_obj.model_dump()
    summary = build_summary(state, report_obj)
    payload: dict[str, Any] = {
        "ok": True,
        "design_phase": str(
            draft.design_phase or state.get("phase") or "intake",
        ),
        "design_summary": summary,
        "validation_report": report,
        "can_compile": bool(report.get("can_compile")),
    }
    if include_full:
        payload["design_state"] = state
    return ToolResult(payload)


read_design_state_tool = FunctionTool(
    name="read_design_state",
    description=(
        "Read the current design_state authoring artifact. Returns "
        "phase, compact summary, full validation report, and a "
        "can_compile flag. Pass `include_full=true` only when you "
        "really need the full structured state -- the summary covers "
        "almost everything you need to plan."
    ),
    json_schema=make_object_schema({
        "include_full": {"type": "boolean"},
    }),
    is_write=False,
    executor=_read_design_state,
)


# ---------------------------------------------------------------------------
# apply_design_ops
# ---------------------------------------------------------------------------


async def _apply_design_ops(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    raw_ops = args.get("ops")
    if not isinstance(raw_ops, list) or not raw_ops:
        raise ToolError(
            "missing_arg",
            "ops (non-empty list of design-state op objects) required",
        )
    try:
        result = await apply_design_ops_to_draft(
            ctx.db,
            draft_id=ctx.draft_id,
            owner_id=ctx.owner_id,
            raw_ops=raw_ops,
            message_id=ctx.assistant_message_id,
        )
    except DesignPatchError as e:
        raise ToolError(
            f"design_patch_{e.code}",
            f"op[{e.op_index}] {e.code}: {e.message}",
        ) from e
    payload = _result_payload(result, write=True)
    return ToolResult(payload, edit_id=result.edit_id)


apply_design_ops_tool = FunctionTool(
    name="apply_design_ops",
    description=(
        "Apply a batch of design_state ops to author the rule design. "
        "This is the ONLY way you may mutate the authoring artifact. "
        "Each op is an object with `op` plus its arguments. Supported "
        "ops: " + ", ".join(_OP_NAMES) + ". The reducer is "
        "all-or-nothing: if any op is invalid, none are applied and "
        "an error code (`design_patch_<code>`) is returned. parsed_v6 "
        "is never mutated by this tool -- run `compile_design` once "
        "the validation report shows can_compile=true."
    ),
    json_schema=_APPLY_DESIGN_OPS_SCHEMA,
    is_write=True,
    executor=_apply_design_ops,
)


# ---------------------------------------------------------------------------
# validate_design_state
# ---------------------------------------------------------------------------


async def _validate_design_state(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    persist = bool(args.get("persist", True))
    result = await validate_design_state_for_draft(
        ctx.db,
        draft_id=ctx.draft_id,
        owner_id=ctx.owner_id,
        persist=persist,
    )
    payload = _result_payload(result, write=False)
    return ToolResult(payload)


validate_design_state_tool = FunctionTool(
    name="validate_design_state",
    description=(
        "Re-run the design_state validator and refresh the persisted "
        "validation_report. Use this after a sequence of edits to "
        "confirm whether compile is unblocked. Read-only with respect "
        "to design_state itself."
    ),
    json_schema=make_object_schema({
        "persist": {"type": "boolean"},
    }),
    is_write=False,
    executor=_validate_design_state,
)


DESIGN_STATE_TOOLS: list[FunctionTool] = [
    read_design_state_tool,
    apply_design_ops_tool,
    validate_design_state_tool,
]


__all__ = ["DESIGN_STATE_TOOLS"]
