"""Unified runtime facade for TRPG CHECK execution.

This module keeps live CHECK paths aligned:

- inline ``[CHECK auto=true]`` replacement
- delayed ``[pending_check ...]`` resolution
- dice history / message metadata trace payloads

Lower-level modules still own parsing and engine arithmetic. The facade owns
runtime spec selection, CoC coercion, boundary dice rolls, rendering, and the
structured trace that downstream code can persist.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from .check_resolver import (
    CheckArgs,
    render_dice_block,
    resolve_check,
)
from .check_house_rules import apply_request_house_rules
from .check_fallbacks import semantic_check_route
from .check_spec_registry import select_check_spec
from .check_runtime_count_expr import needs_auto_roll
from .check_runtime_ir import (
    _clone_args,
    _roll_auxiliary_ir_sources,
    _roll_expression_for_existing,
    _roll_expression_for_source,
    _roll_from_ir,
    _roll_pool,
    _roll_sources_for_existing,
)
from .check_runtime_models import (
    CheckExecution,
    RollSample,
    RollTrace,
    RuntimeCheckContext,
)
from .check_runtime_pending import (
    _PENDING_BASE_EXTRA_KEYS,
    _encode_pending_extra_value,
    _quote_attr,
    _should_emit_pending_extra,
)
from .check_runtime_traces import (
    _build_trace,
    _ensure_roll_seed,
    _roll_seed,
)
from .coc_runtime import coerce_coc_d100_check_spec
from .dice_roller import DiceRoller


__all__ = [
    "CheckExecution",
    "RollSample",
    "RollTrace",
    "RuntimeCheckContext",
    "auto_roll_for_check",
    "execute_check_runtime",
    "needs_auto_roll",
    "prepare_check_context",
    "render_pending_check",
]


def prepare_check_context(
    args: CheckArgs,
    runtime_spec: dict[str, Any] | None,
    *,
    procedure_id: str = "",
    system: Any = None,
) -> RuntimeCheckContext:
    """Select and coerce the runtime spec for one CHECK."""

    requested = (
        str(procedure_id or "").strip()
        or str((args.extras or {}).get("procedure_id") or "").strip()
    )
    selected: dict[str, Any] | None = None
    if not requested:
        route = semantic_check_route(args, runtime_spec or {})
        if route is not None:
            requested = route.procedure_id
            selected = copy.deepcopy(route.spec) if route.spec else None
    if selected is None:
        selected = select_check_spec(runtime_spec or {}, requested)
    selected_pid = str(selected.get("_runtime_procedure_id") or "").strip()
    spec = coerce_coc_d100_check_spec(selected, system=system)
    resolved_pid = (
        str(spec.get("_runtime_procedure_id") or "").strip()
        or selected_pid
        or requested
    )
    if resolved_pid and "_runtime_procedure_id" not in spec:
        spec["_runtime_procedure_id"] = resolved_pid
    engine = str((spec or {}).get("engine") or "custom_llm").strip().lower()
    return RuntimeCheckContext(
        spec=spec,
        requested_procedure_id=requested,
        procedure_id=resolved_pid,
        engine=engine or "custom_llm",
    )


def auto_roll_for_check(args: CheckArgs, spec: dict[str, Any]) -> RollSample:
    """Generate runtime dice for a CHECK and name the source expression."""

    seed = _ensure_roll_seed(args)
    roller = DiceRoller(seed=seed)
    pool_roll = _roll_pool(args.pool, roller=roller)
    if pool_roll is not None:
        expr = str(args.pool or "").strip()
        return RollSample(
            pool_roll.resolver_value(),
            pool_roll.expression or expr,
            roll_sources={"roll": pool_roll.resolver_value()},
            roll_expressions={"roll": expr},
            roll_traces={"roll": pool_roll.to_metadata()},
            seed=seed,
        )

    engine = str((spec or {}).get("engine") or "").strip().lower()
    if engine == "generic_resolution_v1":
        ir_roll = _roll_from_ir(args, spec, roller=roller, seed=seed)
        if ir_roll is not None:
            return ir_roll
    if engine in {"coc_7e_d100", "brp_d100"} or "d100" in engine:
        if engine == "coc_7e_d100" and (args.bonus or args.penalty):
            result = roller.roll_coc_d100(
                bonus=int(args.bonus or 0),
                penalty=int(args.penalty or 0),
            )
        else:
            result = roller.roll("d100")
        return RollSample(
            result.resolver_value(),
            "d100",
            roll_sources={"roll": result.resolver_value()},
            roll_expressions={"roll": "d100"},
            roll_traces={"roll": result.to_metadata()},
            seed=seed,
            extra_args={"coc_bonus_penalty_resolved": bool(args.bonus or args.penalty)},
        )
    if engine == "pbta_2d6":
        result = roller.roll("2d6")
        return RollSample(
            result.resolver_value(),
            "2d6",
            roll_sources={"roll": result.resolver_value()},
            roll_expressions={"roll": "2d6"},
            roll_traces={"roll": result.to_metadata()},
            seed=seed,
        )
    result = roller.roll("1d20")
    return RollSample(
        result.resolver_value(),
        "1d20",
        roll_sources={"roll": result.resolver_value()},
        roll_expressions={"roll": "1d20"},
        roll_traces={"roll": result.to_metadata()},
        seed=seed,
    )


def execute_check_runtime(
    args: CheckArgs,
    runtime_spec: dict[str, Any] | None,
    *,
    procedure_id: str = "",
    system: Any = None,
    auto_roll: bool = False,
    source: str = "check_runtime",
) -> CheckExecution:
    """Resolve, render, and trace one CHECK through the unified runtime."""

    work_args = _clone_args(args)
    context = prepare_check_context(
        work_args,
        runtime_spec,
        procedure_id=procedure_id,
        system=system,
    )
    work_args = apply_request_house_rules(work_args, context.spec)
    auto_rolled = False
    roll_expression = _roll_expression_for_existing(work_args, context.spec)
    roll_sources = _roll_sources_for_existing(work_args, context.spec)
    roll_expressions = {
        key: _roll_expression_for_source(key, work_args, context.spec)
        for key in roll_sources
    }
    roll_traces: dict[str, Any] = {}
    roll_seed = _roll_seed(work_args)
    if auto_roll and needs_auto_roll(work_args.roll):
        sample = auto_roll_for_check(work_args, context.spec)
        work_args.roll = sample.value
        work_args.extras.update(sample.extra_args or {})
        for key, value in sample.roll_sources.items():
            if key != "roll":
                work_args.extras[key] = value
        roll_expression = sample.expression
        roll_sources = sample.roll_sources or {sample.source_arg: sample.value}
        roll_expressions = sample.roll_expressions or {sample.source_arg: sample.expression}
        roll_traces = sample.roll_traces or {}
        roll_seed = sample.seed
        auto_rolled = True

    if not needs_auto_roll(work_args.roll):
        aux_sample = _roll_auxiliary_ir_sources(work_args, context.spec, seed=roll_seed)
        if aux_sample is not None:
            work_args.extras.update(aux_sample.extra_args or {})
            roll_sources.update(aux_sample.roll_sources or {})
            roll_expressions.update(aux_sample.roll_expressions or {})
            roll_traces.update(aux_sample.roll_traces or {})
            roll_seed = aux_sample.seed or roll_seed

    result = resolve_check(work_args, context.spec)
    rendered = render_dice_block(work_args, result)
    trace = _build_trace(
        source=source,
        context=context,
        args=work_args,
        result=result,
        roll_expression=roll_expression,
        roll_expressions=roll_expressions,
        roll_sources=roll_sources,
        roll_trace=roll_traces,
        roll_seed=roll_seed,
        auto_rolled=auto_rolled,
    )
    return CheckExecution(
        args=work_args,
        spec=context.spec,
        result=result,
        rendered=rendered,
        trace=trace,
    )


def render_pending_check(
    args: CheckArgs,
    spec: dict[str, Any],
    *,
    procedure_id: str = "",
) -> str:
    """Emit a parseable ``[pending_check ...]`` placeholder."""

    engine = str((spec or {}).get("engine") or "").strip().lower() or "custom_llm"
    check_id = uuid.uuid4().hex[:12]
    roll_seed = (
        str((args.extras or {}).get("roll_seed") or "").strip()
        or str((args.extras or {}).get("seed") or "").strip()
        or f"pending:{check_id}"
    )
    pieces: list[str] = [f"id={_quote_attr(check_id)}"]
    pieces.append(f"engine={_quote_attr(engine)}")
    pieces.append(f"roll_seed={_quote_attr(roll_seed)}")
    pid = (
        procedure_id
        or str((args.extras or {}).get("procedure_id") or "").strip()
        or str(spec.get("_runtime_procedure_id") or "").strip()
    )
    if pid:
        pieces.append(f"procedure_id={_quote_attr(pid)}")
    if args.skill:
        pieces.append(f"skill={_quote_attr(args.skill)}")
    if args.value is not None:
        pieces.append(f"value={args.value}")
    pieces.append(f"difficulty={_quote_attr(args.difficulty or 'regular')}")
    if args.target is not None:
        pieces.append(f"target={args.target}")
    if args.pool:
        pieces.append(f"pool={_quote_attr(args.pool)}")
    if args.bonus:
        pieces.append(f"bonus={args.bonus}")
    if args.penalty:
        pieces.append(f"penalty={args.penalty}")
    if args.reason:
        pieces.append(f"reason={_quote_attr(args.reason)}")
    for key in _PENDING_BASE_EXTRA_KEYS:
        value = (args.extras or {}).get(key)
        if value not in (None, ""):
            pieces.append(f"{key}={_quote_attr(value)}")
    for key, value in sorted((args.extras or {}).items()):
        if not _should_emit_pending_extra(key, value):
            continue
        pieces.append(f"{key}={_quote_attr(_encode_pending_extra_value(value))}")
    return "[pending_check " + " ".join(pieces) + "]"
