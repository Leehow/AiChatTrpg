"""Result-axis computation for the dice-rule IR interpreter.

Turns the post-step ``ctx`` into the public ``axes`` map, picks the primary
axis tier, and builds the human-readable explanation/roll-display strings the
entry function returns.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .core_expr import _eval_scalar_expr
from .core_runtime import _condition_matches, _resolve_value
from .core_types import DiceIRValidationError, Die


def _compute_axes(axes_spec: Any, ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(axes_spec, list) or not axes_spec:
        raise DiceIRValidationError("result_axes must be a non-empty array")
    axes: Dict[str, Dict[str, Any]] = {}
    for axis in axes_spec:
        if not isinstance(axis, Mapping):
            raise DiceIRValidationError("result axis must be an object")
        axis_id = str(axis.get("id") or "")
        if not axis_id:
            raise DiceIRValidationError("result axis missing id")
        kind = str(axis.get("kind") or "value")
        if kind == "pass_fail":
            passed = _condition_matches(axis.get("pass_when") or {}, ctx)
            tier = axis.get("success_tier" if passed else "failure_tier") or (
                "success" if passed else "failure"
            )
            axes[axis_id] = {
                "kind": kind,
                "value": bool(passed),
                "passed": bool(passed),
                "tier": str(tier),
            }
        elif kind == "tier":
            matched = _pick_tier(axis.get("outcomes") or [], ctx)
            axes[axis_id] = {
                "kind": kind,
                "value": matched.get("tier"),
                "passed": bool(matched.get("passed", False)),
                "tier": matched.get("tier"),
            }
        elif kind == "flags":
            flags = _pick_flags(axis.get("flags") or [], ctx)
            axes[axis_id] = {
                "kind": kind,
                "value": [flag["id"] for flag in flags],
                "active": bool(flags),
                "flags": flags,
            }
        elif kind in {"resource_delta", "complication", "narrative_positive", "value"}:
            value = _axis_value(axis, ctx)
            axes[axis_id] = {
                "kind": kind,
                "value": value,
                "active": bool(value),
            }
        else:
            raise DiceIRValidationError(f"unsupported result axis kind: {kind}")
    return axes


def _pick_tier(outcomes: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(outcomes, list):
        raise DiceIRValidationError("tier axis requires outcomes array")
    default: Optional[Mapping[str, Any]] = None
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            continue
        if outcome.get("default") is True:
            default = outcome
            continue
        if _condition_matches(outcome.get("when") or {}, ctx):
            return dict(outcome)
    return dict(default or {"tier": "failure", "passed": False})


def _pick_flags(flags_spec: Any, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(flags_spec, list):
        raise DiceIRValidationError("flags axis requires flags array")
    flags: List[Dict[str, Any]] = []
    for flag in flags_spec:
        if not isinstance(flag, Mapping):
            continue
        if _condition_matches(flag.get("when") or {}, ctx):
            flag_id = str(flag.get("id") or flag.get("tier") or flag.get("label") or "")
            if not flag_id:
                raise DiceIRValidationError("flag requires id")
            flags.append({
                "id": flag_id,
                "label": flag.get("label") or flag_id,
                "tier": flag.get("tier") or flag_id,
            })
    return flags


def _axis_value(axis: Mapping[str, Any], ctx: Dict[str, Any]) -> Any:
    if "expr" in axis:
        return _eval_scalar_expr(str(axis["expr"]), ctx)
    if "from" in axis:
        return _resolve_value(axis["from"], ctx)
    if "value" in axis:
        return _resolve_value(axis["value"], ctx)
    return 0


def _pick_primary_axis(axes: Mapping[str, Mapping[str, Any]]) -> str:
    for key, axis in axes.items():
        if axis.get("kind") in {"pass_fail", "tier"}:
            return key
    return next(iter(axes), "")


def _roll_display(groups: Mapping[str, List[Die]]) -> str:
    if not groups:
        return ""
    first_key = next(iter(groups))
    return ", ".join(str(die.value) for die in groups[first_key])


def _build_explanation(
    ctx: Mapping[str, Any],
    axes: Mapping[str, Mapping[str, Any]],
    primary_axis: str,
    labels: Mapping[str, Any],
) -> str:
    var_bits = [f"{key}={value}" for key, value in ctx["vars"].items()]
    axis_bits: List[str] = []
    for axis_id, axis in axes.items():
        if axis_id == primary_axis:
            tier = axis.get("tier") or axis.get("value")
            axis_bits.append(f"{axis_id}={labels.get(tier, tier)}")
    return "；".join(var_bits + axis_bits)
