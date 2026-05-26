"""ChatLab TRPG adapter for the portable dice-rule IR interpreter."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ..check_engine_registry import register_engine
from ..check_resolver import CheckArgs, CheckResult
from .core import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    run_resolution_ir,
)


def resolve_generic_ir(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    """Resolve a ``generic_resolution_v1`` check_spec through check_ir.core."""

    ir = (spec or {}).get("ir") or {}
    if not isinstance(ir, dict):
        return CheckResult(
            tier="unresolved",
            tier_label="需人工判定",
            passed=False,
            explanation="generic_resolution_v1 missing ir object",
            warnings=["generic_resolution_v1 missing ir"],
            engine="generic_resolution_v1",
            roll_display=str(args.roll or "?"),
        )

    runtime_args = _runtime_args_for_ir(args, ir)

    try:
        out = run_resolution_ir(ir, runtime_args)
    except DiceIRManualResolutionRequired as e:
        return CheckResult(
            tier="manual_resolution_required",
            tier_label="需人工选择",
            passed=False,
            explanation=f"需要补充选择输入: {e}",
            warnings=[str(e)],
            engine="generic_resolution_v1",
            roll_display=str(args.roll or "?"),
            result_axes={"_ir_error": str(e), "_runtime_args": runtime_args},
        )
    except (DiceIRValidationError, DiceIRExecutionError) as e:
        msg = str(e)
        if "missing required runtime arg: target" in msg:
            explanation = "IR 需要 target 参数但 marker 未提供；仅显示骰值，并以叙事结果为准。"
        else:
            explanation = "IR 暂时无法自动完成该判定；仅显示骰值，并以叙事结果为准。"
        return CheckResult(
            tier="unresolved",
            tier_label="仅显示骰值",
            passed=False,
            explanation=explanation,
            warnings=[str(e)],
            engine="generic_resolution_v1",
            roll_display=str(args.roll or "?"),
            result_axes={"_ir_error": str(e), "_runtime_args": runtime_args},
        )

    labels = ir.get("labels") if isinstance(ir.get("labels"), dict) else {}
    tier = str(out.get("primary_tier") or "unresolved")
    side_effects = out.get("side_effects") if isinstance(out.get("side_effects"), dict) else {}
    axes = out.get("axes") if isinstance(out.get("axes"), dict) else {}
    result_axes = dict(axes)
    result_axes["_ir"] = {
        "id": out.get("id") or "",
        "name": out.get("name") or "",
        "primary_axis": out.get("primary_axis") or "",
        "pass_axis": out.get("pass_axis") or "",
        "trace": out.get("trace") if isinstance(out.get("trace"), list) else [],
        "groups": out.get("groups") if isinstance(out.get("groups"), dict) else {},
        "vars": out.get("vars") if isinstance(out.get("vars"), dict) else {},
        "runtime_args": runtime_args,
    }
    return CheckResult(
        tier=tier,
        tier_label=str(labels.get(tier) or out.get("primary_label") or tier),
        passed=bool(out.get("passed")),
        explanation=str(out.get("explanation") or ""),
        thresholds={},
        warnings=[str(w) for w in out.get("warnings") or []],
        engine="generic_resolution_v1",
        roll_display=str(out.get("roll_display") or args.roll or ""),
        side_effects=side_effects,
        result_axes=result_axes,
    )


def _runtime_args_for_ir(args: CheckArgs, ir: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize CHECK marker fields into the IR input contract shape."""

    runtime_args: Dict[str, Any] = {
        "skill": args.skill,
        "skill_label": args.skill,
        "value": args.value,
        "roll": args.roll,
        "difficulty": args.difficulty,
        "bonus": args.bonus,
        "penalty": args.penalty,
        "pool": args.pool,
        "target": args.target,
        "reason": args.reason,
    }
    runtime_args.update(getattr(args, "extras", {}) or {})
    _apply_skill_aliases(runtime_args)
    _apply_value_aliases(runtime_args)
    _apply_target_aliases(runtime_args)
    _apply_resource_aliases(runtime_args)
    _fan_out_roll_sources(runtime_args, ir)
    return runtime_args


def _apply_skill_aliases(runtime_args: Dict[str, Any]) -> None:
    label = (
        runtime_args.get("skill")
        or runtime_args.get("check")
        or runtime_args.get("check_key")
        or runtime_args.get("param")
    )
    if label in (None, ""):
        return
    for alias in (
        "characteristic",
        "ability",
        "attribute",
        "check_name",
        "stat",
        "trait",
    ):
        runtime_args.setdefault(alias, label)


def _apply_value_aliases(runtime_args: Dict[str, Any]) -> None:
    if runtime_args.get("value") in (None, ""):
        return
    for alias in (
        "target_value",
        "luck_value",
        "san_value",
        "int_value",
        "firearm_skill",
        "current_skill",
        "first_aid_skill",
        "medicine_skill",
        "standard_value",
        "skill_value",
        "skill_or_characteristic",
        "ability_value",
        "attribute_value",
        "current_sanity",
        "sanity_value",
        "modifier",
        "ability_mod",
        "rating",
    ):
        runtime_args.setdefault(alias, runtime_args["value"])


def _apply_target_aliases(runtime_args: Dict[str, Any]) -> None:
    if runtime_args.get("target") in (None, ""):
        return
    for alias in (
        "target_number",
        "caster_success_value",
        "dc",
        "dv",
        "difficulty_number",
        "difficulty_value",
    ):
        runtime_args.setdefault(alias, runtime_args["target"])


def _apply_resource_aliases(runtime_args: Dict[str, Any]) -> None:
    """Bridge common resource-loss names emitted by generic IR compilers."""

    alias_pairs = (
        ("success_san_loss", "san_loss_success"),
        ("success_san_loss", "sanity_loss_success"),
        ("failure_san_loss", "san_loss_failure"),
        ("failure_san_loss", "sanity_loss_failure"),
        ("max_failure_san_loss", "san_loss_failure_max"),
        ("max_failure_san_loss", "failure_san_loss_max"),
    )
    for source, alias in alias_pairs:
        if runtime_args.get(source) not in (None, ""):
            runtime_args.setdefault(alias, runtime_args[source])
        elif runtime_args.get(alias) not in (None, ""):
            runtime_args.setdefault(source, runtime_args[alias])


def _fan_out_roll_sources(runtime_args: Dict[str, Any], ir: Mapping[str, Any]) -> None:
    """Copy the primary roll into IR-specific source args when needed.

    Directly compiled procedures may use source args like ``action_roll`` or
    ``challenge_roll``. The runtime facade now fills those explicitly for
    auto-rolls; this fallback keeps manually supplied ``roll=...`` markers
    compatible with those procedures too.
    """

    primary_roll = runtime_args.get("roll")
    if primary_roll in (None, ""):
        return
    steps = ir.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, Mapping) or step.get("op") != "read_rolls":
            continue
        source_arg = str(step.get("source_arg") or "roll").strip() or "roll"
        runtime_args.setdefault(source_arg, primary_roll)


register_engine(
    "generic_resolution_v1",
    resolve_generic_ir,
    default_labels={
        "critical": "暴击",
        "triscendence": "Triscendence",
        "success": "成功",
        "partial": "部分成功",
        "failure": "失败",
        "miss": "失败",
        "fumble": "大失败",
        "manual_resolution_required": "需人工选择",
        "unresolved": "仅显示骰值",
    },
)
