"""Step-op handlers for the dice-rule IR interpreter.

Each ``_step_*`` function reads/writes the shared ``ctx`` produced by
``core.run_resolution_ir`` and emits a trace entry. ``_run_step`` is the
dispatcher used by the entry function.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping

from .core_expr import _eval_scalar_expr
from .core_runtime import (
    _coerce_roll_values,
    _coerce_int_list,
    _condition_matches,
    _die_matches,
    _group,
    _optional_indices,
    _resolve_dice_like_value,
    _resolve_value,
    _trace,
    _values,
    _write_var,
)
from .core_types import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    Die,
)


_DICE_EXPR_RE = re.compile(r"^(?P<count>\d+|N)?d(?P<sides>\d+)$", re.I)


def _run_step(step: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    op = str(step.get("op") or "").strip()
    if not op:
        raise DiceIRValidationError("step missing op")
    handlers = {
        "read_rolls": _step_read_rolls,
        "tally": _step_tally,
        "count": _step_tally,
        "sum_values": _step_sum_values,
        "max_value": _step_max_value,
        "formula": _step_formula,
        "conditional_value": _step_conditional_value,
        "resolve_dice_value": _step_resolve_dice_value,
        "change_die_to_value": _step_change_die_to_value,
        "remove_matches": _step_remove_matches,
        "select_keep": _step_select_keep,
        "weighted_success_count": _step_weighted_success_count,
        "beat_count": _step_beat_count,
        "degree_count": _step_degree_count,
    }
    fn = handlers.get(op)
    if not fn:
        raise DiceIRValidationError(f"unsupported step op: {op}")
    fn(step, ctx)


def _step_read_rolls(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    group_id = str(step.get("group") or step.get("id") or "")
    if not group_id:
        raise DiceIRValidationError("read_rolls step requires group")
    expr = str(step.get("expr") or "")
    count, sides = _parse_dice_expr(expr, step, ctx)
    source_arg = str(step.get("source_arg") or "roll")
    raw_values = _coerce_roll_values(ctx["args"].get(source_arg))
    if len(raw_values) < count:
        raise DiceIRExecutionError(
            f"read_rolls group {group_id} needs {count} values, got {len(raw_values)}"
        )
    tags = [str(x) for x in (step.get("tags") or [])]
    faceset = str(step.get("faceset") or f"d{sides}")
    dice = [
        Die(
            id=f"{group_id}.{idx}",
            value=int(value),
            sides=sides,
            faceset=faceset,
            source_group=group_id,
            tags=list(tags),
            original_value=int(value),
        )
        for idx, value in enumerate(raw_values[:count])
    ]
    ctx["groups"][group_id] = dice
    _trace(ctx, step, f"{group_id}={_values(dice)}")


def _step_tally(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    dice = _group(ctx, str(step.get("from") or ""))
    where = step.get("where") if isinstance(step.get("where"), Mapping) else {}
    value = sum(1 for die in dice if die.kept and _die_matches(die, where, ctx))
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_sum_values(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    dice = _group(ctx, str(step.get("from") or ""))
    value = sum(die.value for die in dice if die.kept)
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_max_value(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    dice = [die for die in _group(ctx, str(step.get("from") or "")) if die.kept]
    value = max((die.value for die in dice), default=0)
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_formula(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    expr = str(step.get("expr") or "")
    if not expr:
        raise DiceIRValidationError("formula step requires expr")
    value = _eval_scalar_expr(expr, ctx)
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_conditional_value(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    cases = step.get("cases")
    if not isinstance(cases, list):
        raise DiceIRValidationError("conditional_value requires cases array")
    value = _resolve_value(step.get("default"), ctx) if "default" in step else None
    for case in cases:
        if isinstance(case, Mapping) and _condition_matches(case.get("when") or {}, ctx):
            value = _resolve_value(case.get("value"), ctx)
            break
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_resolve_dice_value(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    raw = _resolve_value(step.get("source"), ctx)
    roll_source_arg = str(step.get("roll_source_arg") or "")
    roll_values = ctx["args"].get(roll_source_arg) if roll_source_arg else None
    value = _resolve_dice_like_value(raw, roll_values, mode=str(step.get("mode") or "value"))
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_change_die_to_value(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    source = str(step.get("from") or "")
    write_group = str(step.get("write_group") or source)
    target_value = int(_resolve_value(step.get("to"), ctx))
    where = step.get("where") if isinstance(step.get("where"), Mapping) else {}
    indices = _optional_indices(step.get("indices_from"), ctx)
    target_values = _optional_indices(step.get("values_from"), ctx)
    count = int(_resolve_value(step.get("count_from", len(indices) if indices else 0), ctx) or 0)
    changed = 0
    out: List[Die] = []
    selected = set(indices[:count]) if indices else set()
    for idx, die in enumerate(_group(ctx, source)):
        new_die = die.copy()
        should_change = (
            (idx in selected) if indices else (changed < count and _die_matches(new_die, where, ctx))
        )
        if should_change and new_die.kept:
            tags = list(new_die.tags)
            if "modified" not in tags:
                tags.append("modified")
            value = target_values[changed] if changed < len(target_values) else target_value
            new_die = new_die.copy(value=int(value), tags=tags)
            changed += 1
        out.append(new_die)
    ctx["groups"][write_group] = out
    if step.get("write"):
        ctx["vars"][str(step["write"])] = changed
    _trace(ctx, step, f"{write_group}={_values(out)} changed={changed}")


def _step_remove_matches(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    source = str(step.get("from") or "")
    write_group = str(step.get("write_group") or source)
    count = int(_resolve_value(step.get("count_from", 0), ctx) or 0)
    where = step.get("where") if isinstance(step.get("where"), Mapping) else {}
    removed = 0
    out: List[Die] = []
    for die in _group(ctx, source):
        new_die = die.copy()
        if removed < count and new_die.kept and _die_matches(new_die, where, ctx):
            tags = list(new_die.tags)
            if "removed" not in tags:
                tags.append("removed")
            new_die = new_die.copy(kept=False, tags=tags)
            removed += 1
        out.append(new_die)
    ctx["groups"][write_group] = out
    if step.get("write"):
        ctx["vars"][str(step["write"])] = removed
    _trace(ctx, step, f"{write_group}={_values(out, kept_marker=True)} removed={removed}")


def _step_select_keep(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    source = str(step.get("from") or "")
    write_group = str(step.get("write_group") or f"{source}_kept")
    dice = [die.copy(kept=False) for die in _group(ctx, source)]
    indices: List[int]
    indices_from = step.get("indices_from")
    if indices_from:
        try:
            raw = _resolve_value(indices_from, ctx)
        except DiceIRExecutionError as e:
            raise DiceIRManualResolutionRequired(
                f"missing choice input for {indices_from}"
            ) from e
        indices = _coerce_int_list(raw)
        if not indices:
            raise DiceIRManualResolutionRequired(f"missing choice input for {indices_from}")
    else:
        count = int(_resolve_value(step.get("count") or step.get("count_from") or 0, ctx) or 0)
        strategy = str(step.get("strategy") or "")
        if count <= 0:
            raise DiceIRManualResolutionRequired("select_keep requires indices or count")
        ranked = sorted(
            enumerate(dice),
            key=lambda item: item[1].value,
            reverse=strategy != "lowest",
        )
        indices = [idx for idx, _die in ranked[:count]]
    for idx in indices:
        if 0 <= idx < len(dice):
            dice[idx] = dice[idx].copy(kept=True)
    ctx["groups"][write_group] = dice
    if step.get("write"):
        ctx["vars"][str(step["write"])] = indices
    _trace(ctx, step, f"{write_group}={_values(dice, kept_marker=True)}")


def _step_weighted_success_count(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    dice = _group(ctx, str(step.get("from") or ""))
    success_where = step.get("success_where") or step.get("where") or {}
    crit_where = step.get("crit_where") or {}
    success_weight = int(step.get("success_weight") or 1)
    crit_weight = int(step.get("crit_weight") or 2)
    complication_where = step.get("complication_where") or {}
    total = 0
    complications = 0
    for die in dice:
        if not die.kept:
            continue
        if isinstance(complication_where, Mapping) and _die_matches(die, complication_where, ctx):
            complications += 1
        if isinstance(crit_where, Mapping) and crit_where and _die_matches(die, crit_where, ctx):
            total += crit_weight
        elif isinstance(success_where, Mapping) and _die_matches(die, success_where, ctx):
            total += success_weight
    _write_var(ctx, step, total)
    if step.get("write_complications"):
        ctx["vars"][str(step["write_complications"])] = complications
    _trace(ctx, step, f"{step.get('write')}={total} complications={complications}")


def _step_beat_count(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    score = _resolve_value(step.get("score"), ctx)
    dice = _group(ctx, str(step.get("challenges") or step.get("from") or ""))
    ties_beat = bool(step.get("ties_beat", False))
    if ties_beat:
        value = sum(1 for die in dice if die.kept and float(score) >= die.value)
    else:
        value = sum(1 for die in dice if die.kept and float(score) > die.value)
    _write_var(ctx, step, value)
    _trace(ctx, step, f"{step.get('write')}={value}")


def _step_degree_count(step: Mapping[str, Any], ctx: Dict[str, Any]) -> None:
    value = float(_resolve_value(step.get("value"), ctx) or 0)
    target = float(_resolve_value(step.get("target"), ctx) or 0)
    step_size = float(_resolve_value(step.get("step_size", 1), ctx) or 1)
    degree = math.floor(max(value - target, 0) / step_size)
    _write_var(ctx, step, degree)
    _trace(ctx, step, f"{step.get('write')}={degree}")


def _parse_dice_expr(expr: str, step: Mapping[str, Any], ctx: Dict[str, Any]) -> tuple[int, int]:
    m = _DICE_EXPR_RE.match(expr.strip())
    if not m:
        raise DiceIRValidationError(f"unsupported dice expr: {expr}")
    sides = int(m.group("sides"))
    raw_count = m.group("count")
    if raw_count and raw_count != "N":
        count = int(raw_count)
    elif step.get("count_from") is not None:
        count = int(_resolve_value(step.get("count_from"), ctx) or 0)
    else:
        count = 1
    if count <= 0:
        # The interpreter keeps zero-dice policies explicit instead of guessing.
        raise DiceIRManualResolutionRequired(f"dice expr {expr} resolved to zero dice")
    if count > 100:
        raise DiceIRExecutionError(f"dice count too large: {count}")
    return count, sides
