"""Generic deterministic dice-rule IR interpreter.

This module is deliberately independent from the ChatLab TRPG runtime. It
accepts a versioned JSON-like IR plus plain runtime arguments and returns a
plain dictionary. The ChatLab-specific adapter lives in ``adapter.py``.

The implementation is split across ``core_*`` modules; this file is the public
facade. Stable importable names: ``DiceIRValidationError``,
``DiceIRExecutionError``, ``DiceIRManualResolutionRequired``, ``Die``,
``run_resolution_ir``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .core_axes import (
    _build_explanation,
    _compute_axes,
    _pick_primary_axis,
    _roll_display,
)
from .core_steps import _run_step
from .core_types import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    Die,
)

__all__ = [
    "DiceIRExecutionError",
    "DiceIRManualResolutionRequired",
    "DiceIRValidationError",
    "Die",
    "run_resolution_ir",
]


def run_resolution_ir(ir: Mapping[str, Any], runtime_args: Mapping[str, Any]) -> Dict[str, Any]:
    """Execute ``resolution_ir_v1_1`` and return a plain result dictionary.

    The returned dictionary is intentionally stable and serializable:

    ``status``
        ``"ok"`` or ``"manual_resolution_required"``.
    ``primary_tier`` / ``passed``
        The UI-friendly main label and pass flag derived from ``primary_axis``.
    ``axes``
        Full multi-axis result map.
    ``trace``
        Step-by-step execution trace for debugging/admin review.
    """

    schema_version = str(ir.get("schema_version") or "")
    if schema_version != "resolution_ir_v1_1":
        raise DiceIRValidationError(f"unsupported schema_version: {schema_version}")

    ctx: Dict[str, Any] = {
        "args": _normalize_args(runtime_args, ir.get("input_contract") or {}),
        "groups": {},
        "vars": {},
        "axes": {},
        "trace": [],
        "warnings": [],
    }

    steps = ir.get("steps")
    if not isinstance(steps, list) or not steps:
        raise DiceIRValidationError("resolution IR requires a non-empty steps array")

    for step in steps:
        if not isinstance(step, Mapping):
            raise DiceIRValidationError("step must be an object")
        _run_step(dict(step), ctx)

    axes = _compute_axes(ir.get("result_axes") or [], ctx)
    ctx["axes"] = axes
    primary_axis = str(ir.get("primary_axis") or _pick_primary_axis(axes))
    primary = axes.get(primary_axis) or {}
    pass_axis_id = str(ir.get("pass_axis") or "")
    pass_axis = axes.get(pass_axis_id) if pass_axis_id else None
    labels = ir.get("labels") if isinstance(ir.get("labels"), Mapping) else {}
    primary_tier = str(
        primary.get("tier")
        or primary.get("value")
        or ("success" if primary.get("passed") else "failure")
    )
    passed_source = pass_axis or primary
    passed = bool(passed_source.get("passed", primary_tier not in {"failure", "miss"}))

    side_effects = {
        axis_id: axis.get("value")
        for axis_id, axis in axes.items()
        if axis_id != primary_axis and axis.get("kind") in {
            "resource_delta", "complication", "narrative_positive", "value",
        }
    }

    return {
        "status": "ok",
        "schema_version": schema_version,
        "id": ir.get("id") or "",
        "name": ir.get("name") or "",
        "primary_axis": primary_axis,
        "pass_axis": pass_axis_id,
        "primary_tier": primary_tier,
        "primary_label": labels.get(primary_tier, primary_tier),
        "passed": passed,
        "axes": axes,
        "side_effects": side_effects,
        "roll_display": _roll_display(ctx["groups"]),
        "explanation": _build_explanation(ctx, axes, primary_axis, labels),
        "trace": list(ctx["trace"]),
        "warnings": list(ctx["warnings"]),
        "groups": {
            key: [die.to_dict() for die in dice]
            for key, dice in ctx["groups"].items()
        },
        "vars": dict(ctx["vars"]),
    }


def _normalize_args(runtime_args: Mapping[str, Any], contract: Mapping[str, Any]) -> Dict[str, Any]:
    args = dict(runtime_args or {})
    optional = contract.get("optional") if isinstance(contract.get("optional"), Mapping) else {}
    for key, spec in optional.items():
        if key not in args and isinstance(spec, Mapping) and "default" in spec:
            args[key] = spec["default"]

    choice_inputs = contract.get("choice_inputs")
    if isinstance(choice_inputs, Mapping):
        for key, spec in choice_inputs.items():
            if key not in args and isinstance(spec, Mapping) and spec.get("required") is True:
                raise DiceIRManualResolutionRequired(f"missing choice input: {key}")

    required = contract.get("required") or []
    for key in required:
        if key not in args or args.get(key) in (None, ""):
            raise DiceIRExecutionError(f"missing required runtime arg: {key}")
    return args
