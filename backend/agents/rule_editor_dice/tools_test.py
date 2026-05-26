"""test_dice_procedure — run synthetic CheckArgs against a compiled
procedure to verify outcomes."""

from __future__ import annotations

import logging
from typing import Any

from agents.trpg.check_resolver import CheckArgs
from agents.trpg.check_runtime import execute_check_runtime
from agents.rule_editor.tools.base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)
from services import ruleset_drafts as svc


logger = logging.getLogger("chatrpg.rule_editor_dice.test_tool")


def _compiled_specs(parsed_v6: dict[str, Any] | None) -> list[dict[str, Any]]:
    v6 = parsed_v6 or {}
    dice_ir = v6.get("dice_ir") or {}
    package = dice_ir.get("package") or {}
    compiled = package.get("compiled") or {}
    specs = compiled.get("check_specs") or []
    return [s for s in specs if isinstance(s, dict) and s.get("procedure_id")]


def _find_check_spec(
    parsed_v6: dict[str, Any] | None, procedure_id: str,
) -> dict[str, Any] | None:
    pid = (procedure_id or "").strip()
    if not pid:
        return None
    for entry in _compiled_specs(parsed_v6):
        if str(entry.get("procedure_id") or "") == pid:
            spec = entry.get("check_spec")
            if isinstance(spec, dict):
                return spec
    return None


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _case_to_check_args(case: dict[str, Any]) -> CheckArgs:
    return CheckArgs(
        skill=str(case.get("skill") or ""),
        value=case.get("value"),
        roll=case.get("roll"),
        difficulty=str(case.get("difficulty") or "regular"),
        bonus=_coerce_int(case.get("bonus") or 0),
        penalty=_coerce_int(case.get("penalty") or 0),
        pool=str(case.get("pool") or "").strip(),
        target=_coerce_optional_int(case.get("target")),
        reason=str(case.get("reason") or "dice_agent_test"),
        extras=dict(case.get("extras") or {}),
    )


def _run_dice_test_case(
    spec: dict[str, Any],
    procedure_id: str,
    case: dict[str, Any],
    *,
    case_index: int,
) -> dict[str, Any]:
    label = case.get("label") if isinstance(case, dict) else None
    if not isinstance(case, dict):
        return {
            "case_index": case_index,
            "label": None,
            "input": case,
            "error": "case must be an object",
        }
    try:
        execution = execute_check_runtime(
            _case_to_check_args(case),
            spec,
            procedure_id=procedure_id,
            auto_roll=False,
            source="dice_agent_test",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[chatrpg] dice agent test case failed")
        return {
            "case_index": case_index,
            "label": label,
            "input": case,
            "error": f"{type(exc).__name__}: {exc}",
        }

    result = execution.result
    trace = execution.trace
    return {
        "case_index": case_index,
        "label": label,
        "input": case,
        "tier": result.tier,
        "tier_label": result.tier_label,
        "passed": bool(result.passed),
        "explanation": result.explanation,
        "roll_display": result.roll_display,
        "warnings": list(result.warnings or []),
        "engine": str(trace.engine or ""),
        "thresholds": dict(result.thresholds or {}),
    }


async def _test_dice_procedure(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    procedure_id = str(args.get("procedure_id") or "").strip()
    cases = args.get("cases") or []
    if not procedure_id:
        raise ToolError("missing_arg", "procedure_id required")
    if not isinstance(cases, list) or not cases:
        raise ToolError("missing_arg", "cases (non-empty list) required")

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    spec = _find_check_spec(draft.parsed_v6, procedure_id)
    if spec is None:
        raise ToolError(
            "procedure_not_found",
            f"procedure `{procedure_id}` not in current dice_ir; design "
            "it first with design_dice_procedure",
        )

    results = [
        _run_dice_test_case(spec, procedure_id, case, case_index=i)
        for i, case in enumerate(cases)
    ]
    return ToolResult({
        "procedure_id": procedure_id,
        "results": results,
        "count_ok": sum(1 for r in results if r.get("passed") is True),
        "count_fail": sum(1 for r in results if r.get("passed") is False),
        "count_error": sum(1 for r in results if r.get("error")),
    })


test_dice_procedure_tool = FunctionTool(
    name="test_dice_procedure",
    description=(
        "Execute synthetic test cases against a compiled procedure. "
        "Each case is a CheckArgs-shaped object; you typically set "
        "`skill` (name), `value` (skill rating, e.g. 50), `roll` "
        "(dice result int or list[int]), and optionally `difficulty` "
        "(regular/hard/extreme/etc.), `bonus`, `penalty`, `pool` "
        "(e.g. '6d4'), `target` (per-die threshold). Returns tier, "
        "passed, explanation per case."
    ),
    json_schema=make_object_schema({
        "procedure_id": {"type": "string"},
        "cases": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
    }, ["procedure_id", "cases"]),
    is_write=False,
    executor=_test_dice_procedure,
)
