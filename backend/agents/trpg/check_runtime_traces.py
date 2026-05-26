"""Trace builders and roll-seed helpers for the CHECK runtime facade."""

from __future__ import annotations

import uuid
from typing import Any

from .check_resolver import CheckArgs, CheckResult, parse_roll_list
from .check_runtime_models import RollTrace, RuntimeCheckContext


def _roll_seed(args: CheckArgs) -> str:
    extras = args.extras or {}
    raw = extras.get("roll_seed")
    if raw in (None, ""):
        raw = extras.get("seed")
    return str(raw or "").strip()


def _ensure_roll_seed(args: CheckArgs) -> str:
    seed = _roll_seed(args)
    if not seed:
        seed = uuid.uuid4().hex
        args.extras = dict(args.extras or {})
        args.extras["roll_seed"] = seed
    return seed


def _roll_total(raw: Any) -> int | None:
    rolls = parse_roll_list(raw)
    if not rolls:
        return None
    if len(rolls) == 1:
        return rolls[0]
    return sum(rolls)


def _trace_warnings(args: CheckArgs, result: CheckResult) -> list[str]:
    out = [str(w) for w in result.warnings or []]
    extra = (args.extras or {}).get("check_warnings")
    if isinstance(extra, list):
        out.extend(str(w) for w in extra if str(w))
    elif extra:
        out.append(str(extra))
    deduped: list[str] = []
    seen: set[str] = set()
    for warning in out:
        if warning in seen:
            continue
        seen.add(warning)
        deduped.append(warning)
    return deduped


def _build_trace(
    *,
    source: str,
    context: RuntimeCheckContext,
    args: CheckArgs,
    result: CheckResult,
    roll_expression: str,
    roll_expressions: dict[str, str],
    roll_sources: dict[str, Any],
    roll_trace: dict[str, Any],
    roll_seed: str,
    auto_rolled: bool,
) -> RollTrace:
    result_axes = dict(result.result_axes or {})
    actor_lookup = (args.extras or {}).get("actor_lookup")
    if isinstance(actor_lookup, dict):
        result_axes["_actor_lookup"] = dict(actor_lookup)
    house_rules = (args.extras or {}).get("_house_rules")
    if isinstance(house_rules, dict):
        result_axes["_house_rules"] = dict(house_rules)
    return RollTrace(
        source=source,
        procedure_id=context.procedure_id,
        requested_procedure_id=context.requested_procedure_id,
        engine=result.engine or context.engine,
        skill=args.skill,
        value=args.value,
        difficulty=args.difficulty or "regular",
        target=args.target,
        pool=args.pool,
        reason=args.reason,
        roll_expression=roll_expression,
        roll_expressions=dict(roll_expressions or {}),
        roll_sources=dict(roll_sources or {}),
        roll_trace=dict(roll_trace or {}),
        roll_seed=roll_seed,
        roll=args.roll,
        roll_total=_roll_total(args.roll),
        roll_display=result.roll_display,
        auto_rolled=auto_rolled,
        tier=result.tier,
        tier_label=result.tier_label,
        passed=result.passed,
        explanation=result.explanation,
        thresholds=dict(result.thresholds or {}),
        warnings=_trace_warnings(args, result),
        side_effects=dict(result.side_effects or {}),
        result_axes=result_axes,
    )
