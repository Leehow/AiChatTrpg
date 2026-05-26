"""IR-driven roll discovery and rendering for the CHECK runtime facade.

These helpers own:

- generic ``read_rolls`` / ``resolve_dice_value`` IR step execution
- auxiliary IR-source rolling (e.g., SAN-loss dice)
- discovery of roll expressions and roll sources for already-supplied rolls
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .check_resolver import CheckArgs
from .check_runtime_count_expr import (
    _arg_value,
    _count_override_for_step,
    _dice_expression_from_value,
    _display_expr,
    _eval_count_expr,
    _resolve_auxiliary_source,
    needs_auto_roll,
)
from .check_runtime_models import RollSample
from .check_runtime_traces import _ensure_roll_seed
from .dice_roller import DiceRollResult, DiceRoller


def _clone_args(args: CheckArgs) -> CheckArgs:
    return CheckArgs(
        skill=args.skill,
        value=args.value,
        roll=args.roll,
        difficulty=args.difficulty,
        bonus=args.bonus,
        penalty=args.penalty,
        pool=args.pool,
        target=args.target,
        reason=args.reason,
        extras=copy.deepcopy(args.extras or {}),
    )


def _roll_pool(pool: str, *, roller: DiceRoller) -> DiceRollResult | None:
    text = str(pool or "").strip()
    if not text:
        return None
    try:
        return roller.roll(text)
    except ValueError:
        return None


def _roll_from_ir(
    args: CheckArgs,
    spec: dict[str, Any],
    *,
    roller: DiceRoller,
    seed: str = "",
) -> RollSample | None:
    ir = spec.get("ir") if isinstance(spec, dict) else None
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if not isinstance(steps, list):
        return None
    roll_sources: dict[str, Any] = {}
    roll_expressions: dict[str, str] = {}
    roll_traces: dict[str, Any] = {}
    vars_seen: dict[str, Any] = {}
    primary_source = ""
    primary_value: Any = None
    primary_expr = ""
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("op") == "formula" and step.get("write"):
            try:
                vars_seen[str(step["write"])] = _eval_count_expr(
                    str(step.get("expr") or "0"),
                    args,
                    vars_seen,
                )
            except Exception:
                pass
            continue
        if step.get("op") == "resolve_dice_value":
            _maybe_roll_auxiliary_ir_step(
                step,
                args,
                roller=roller,
                vars_seen=vars_seen,
                roll_sources=roll_sources,
                roll_expressions=roll_expressions,
                roll_traces=roll_traces,
            )
            continue
        if step.get("op") != "read_rolls":
            continue
        source_arg = str(step.get("source_arg") or "roll").strip() or "roll"
        expr = str(step.get("expr") or "")
        count_override = _count_override_for_step(step, args, vars_seen)
        display_expr = _display_expr(expr, count_override)
        try:
            rolled = roller.roll(display_expr)
        except ValueError:
            continue
        if rolled is not None:
            source_value = rolled.resolver_value()
            roll_sources[source_arg] = source_value
            roll_expressions[source_arg] = display_expr
            roll_traces[source_arg] = rolled.to_metadata()
            if not primary_source:
                primary_source = source_arg
                primary_value = source_value
                primary_expr = roll_expressions[source_arg]
    if not primary_source:
        return None
    return RollSample(
        primary_value,
        primary_expr,
        source_arg=primary_source,
        roll_sources=roll_sources,
        roll_expressions=roll_expressions,
        roll_traces=roll_traces,
        seed=seed,
    )


def _roll_auxiliary_ir_sources(
    args: CheckArgs,
    spec: dict[str, Any],
    *,
    seed: str = "",
) -> RollSample | None:
    """Roll missing non-primary IR dice sources, such as SAN loss dice."""

    engine = str((spec or {}).get("engine") or "").strip().lower()
    if engine != "generic_resolution_v1":
        return None
    ir = spec.get("ir") if isinstance(spec, dict) else None
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if not isinstance(steps, list):
        return None
    resolved_seed = seed or _ensure_roll_seed(args)
    roller = DiceRoller(seed=f"{resolved_seed}:aux")
    roll_sources: dict[str, Any] = {}
    roll_expressions: dict[str, str] = {}
    roll_traces: dict[str, Any] = {}
    vars_seen: dict[str, Any] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("op") == "formula" and step.get("write"):
            try:
                vars_seen[str(step["write"])] = _eval_count_expr(
                    str(step.get("expr") or "0"),
                    args,
                    vars_seen,
                )
            except Exception:
                pass
            continue
        if step.get("op") != "resolve_dice_value":
            continue
        _maybe_roll_auxiliary_ir_step(
            step,
            args,
            roller=roller,
            vars_seen=vars_seen,
            roll_sources=roll_sources,
            roll_expressions=roll_expressions,
            roll_traces=roll_traces,
        )
    if not roll_sources:
        return None
    return RollSample(
        None,
        "",
        source_arg="",
        roll_sources=roll_sources,
        roll_expressions=roll_expressions,
        roll_traces=roll_traces,
        seed=resolved_seed,
        extra_args=dict(roll_sources),
    )


def _maybe_roll_auxiliary_ir_step(
    step: Mapping[str, Any],
    args: CheckArgs,
    *,
    roller: DiceRoller,
    vars_seen: Mapping[str, Any],
    roll_sources: dict[str, Any],
    roll_expressions: dict[str, str],
    roll_traces: dict[str, Any],
) -> None:
    source_arg = str(step.get("roll_source_arg") or "").strip()
    if not source_arg or source_arg == "roll":
        return
    if source_arg in roll_sources:
        return
    if _arg_value(args, source_arg) not in (None, ""):
        return
    expr = _dice_expression_from_value(
        _resolve_auxiliary_source(step.get("source"), args, vars_seen)
    )
    if not expr:
        return
    try:
        rolled = roller.roll(expr)
    except ValueError:
        return
    roll_sources[source_arg] = rolled.resolver_value()
    roll_expressions[source_arg] = expr
    roll_traces[source_arg] = rolled.to_metadata()


def _roll_expression_for_existing(
    args: CheckArgs,
    spec: dict[str, Any],
) -> str:
    if args.pool:
        return str(args.pool).strip()
    engine = str((spec or {}).get("engine") or "").strip().lower()
    if engine in {"coc_7e_d100", "brp_d100"} or "d100" in engine:
        return "1d100"
    if engine == "pbta_2d6":
        return "2d6"
    if engine == "d20_vs_dc":
        return "1d20"
    if engine == "generic_resolution_v1":
        ir = spec.get("ir") if isinstance(spec, dict) else None
        steps = ir.get("steps") if isinstance(ir, dict) else None
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and step.get("op") == "read_rolls":
                    return str(step.get("expr") or "").strip()
    return ""


def _roll_expression_for_source(
    source_arg: str,
    args: CheckArgs,
    spec: dict[str, Any],
) -> str:
    if source_arg == "roll":
        return _roll_expression_for_existing(args, spec)
    ir = spec.get("ir") if isinstance(spec, dict) else None
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("op") != "read_rolls":
                continue
            if str(step.get("source_arg") or "roll") == source_arg:
                return str(step.get("expr") or "").strip()
        for step in steps:
            if not isinstance(step, dict) or step.get("op") != "resolve_dice_value":
                continue
            if str(step.get("roll_source_arg") or "").strip() != source_arg:
                continue
            expr = _dice_expression_from_value(
                _resolve_auxiliary_source(step.get("source"), args, {})
            )
            if expr:
                return expr
    return ""


def _roll_sources_for_existing(
    args: CheckArgs,
    spec: dict[str, Any],
) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    if not needs_auto_roll(args.roll):
        sources["roll"] = args.roll
    ir = spec.get("ir") if isinstance(spec, dict) else None
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("op") != "read_rolls":
                continue
            source_arg = str(step.get("source_arg") or "roll").strip() or "roll"
            if source_arg == "roll":
                continue
            value = (args.extras or {}).get(source_arg)
            if value not in (None, ""):
                sources[source_arg] = value
        for step in steps:
            if not isinstance(step, dict) or step.get("op") != "resolve_dice_value":
                continue
            source_arg = str(step.get("roll_source_arg") or "").strip()
            if not source_arg or source_arg == "roll":
                continue
            value = (args.extras or {}).get(source_arg)
            if value not in (None, ""):
                sources[source_arg] = value
    return sources
