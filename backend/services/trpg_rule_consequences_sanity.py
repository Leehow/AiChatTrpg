"""CoC 7e sanity-check rule consequences.

Handles SAN-loss bookkeeping that the dice IR / check runtime cannot express
on its own:
- Decrement the actor's sanity resource.
- On a single loss of 5 or more, run the temporary-insanity INT check
  (recursion-guarded) and decide whether a temporary-insanity bout follows.
- Maintain the per-day SAN-loss counter and flag indefinite insanity when the
  loss-since-day-start exceeds floor(start_sanity / 5).
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from agents.trpg.check_actor_adapter import (
    apply_actor_value_lookup,
    build_actor_lookup_context,
)
from agents.trpg.check_resolver import CheckArgs
from agents.trpg.check_runtime import CheckExecution, execute_check_runtime

from services.trpg_rule_consequences_catalog import actor_id, axis_facts
from services.trpg_rule_consequences_resource import (
    actor_root,
    apply_resource_delta,
    dedupe,
    lookup_named_numeric,
    number,
    safe_flag_modified,
)


RULE_CONSEQUENCE_FOLLOWUP_SOURCE = "rule_consequence_followup"


def apply_coc_sanity_consequence(
    session: Any,
    check_log: Any,
    execution: CheckExecution,
    *,
    runtime_spec: dict[str, Any] | None,
    allow_followup: bool,
) -> tuple[list[dict[str, Any]], list[CheckExecution]]:
    """Return (consequence_events, followup_executions) for one CHECK.

    The caller owns merging these into the broader result aggregate.
    """

    if not _looks_like_sanity_check(check_log, execution):
        return [], []

    delta, loss = _sanity_delta_and_loss(execution)
    if delta is None or loss <= 0:
        return [], []

    actor = actor_id(check_log, execution)
    before_hint = _sanity_before_hint(execution)
    resource_change = apply_resource_delta(
        session,
        actor,
        resource="sanity",
        delta=delta,
        before_hint=before_hint,
        path_candidates=_sanity_path_candidates(),
        clamp_min=0,
    )

    flags: list[str] = []
    followup_checks: list[dict[str, Any]] = []
    followup_executions: list[CheckExecution] = []
    insanity: dict[str, Any] | None = None

    if loss >= 5:
        flags.append("temporary_insanity_check_required")
        followup = {
            "procedure_id": "coc7.characteristic_check",
            "skill": "INT",
            "mandatory": True,
            "auto": True,
            "reason": "Single SAN loss >= 5 requires an INT check for temporary insanity.",
        }
        if allow_followup:
            followup_execution = _execute_temporary_insanity_int_check(
                session,
                actor,
                runtime_spec=runtime_spec,
                source_execution=execution,
            )
            if followup_execution is None:
                followup["status"] = "missing_int_value"
            else:
                followup_executions.append(followup_execution)
                followup["status"] = "resolved"
                followup["result"] = _followup_result_summary(followup_execution)
                if followup_execution.result.passed:
                    flags.append("temporary_insanity")
                    insanity = {
                        "kind": "temporary",
                        "bout_required": True,
                        "underlying_duration_expr": "1d10 hours",
                    }
                else:
                    flags.append("temporary_insanity_repressed")
                    insanity = {
                        "kind": "temporary_check_repressed",
                        "bout_required": False,
                    }
        else:
            followup["status"] = "suppressed_by_recursion_guard"
        followup_checks.append(followup)

    daily = _apply_daily_sanity_counter(
        session,
        loss=loss,
        day_start_hint=resource_change.get("before"),
    )
    if daily.get("triggered_indefinite"):
        flags.append("indefinite_insanity")
        if insanity is None:
            insanity = {}
        insanity.update({
            "kind": "indefinite",
            "bout_required": True,
            "recovery_required": True,
        })

    event: dict[str, Any] = {
        "id": f"{getattr(check_log, 'id', '') or uuid.uuid4().hex}:sanity",
        "type": "sanity_consequence",
        "system_id": "coc7",
        "actor_id": actor or "pc",
        "source_check_log_id": str(getattr(check_log, "id", "") or ""),
        "procedure_id": str(getattr(check_log, "procedure_id", "") or execution.trace.procedure_id),
        "resource_changes": [resource_change] if resource_change else [],
        "flags": dedupe(flags),
        "followup_checks": followup_checks,
        "daily_counter": daily,
        "narration_contract": {
            "llm_may_narrate": True,
            "llm_must_not_recompute_rules": True,
            "style": "horror_consequence",
        },
    }
    if insanity:
        event["insanity"] = insanity
    return [event], followup_executions


def _execute_temporary_insanity_int_check(
    session: Any,
    actor_id_value: str,
    *,
    runtime_spec: dict[str, Any] | None,
    source_execution: CheckExecution,
) -> CheckExecution | None:
    args = CheckArgs(
        skill="INT",
        difficulty="regular",
        reason="Single SAN loss >= 5: INT check for temporary insanity",
        extras={
            "actor": actor_id_value or "pc",
            "roll_seed": f"{source_execution.trace.roll_seed or uuid.uuid4().hex}:temporary_insanity_int",
            "_consequence_followup": True,
        },
    )
    args = apply_actor_value_lookup(args, build_actor_lookup_context(session))
    if args.value in (None, ""):
        args.value = _lookup_int_value(session, actor_id_value)
    if args.value in (None, ""):
        return None

    procedure_id = _select_followup_procedure(runtime_spec)
    spec = runtime_spec if isinstance(runtime_spec, dict) else {"engine": "coc_7e_d100"}
    if not _procedure_exists(spec, procedure_id):
        spec = {"engine": "coc_7e_d100"}
    return execute_check_runtime(
        args,
        spec,
        procedure_id=procedure_id,
        system="coc_7e_d100",
        auto_roll=True,
        source=RULE_CONSEQUENCE_FOLLOWUP_SOURCE,
    )


def _select_followup_procedure(runtime_spec: dict[str, Any] | None) -> str:
    for pid in (
        "coc7.temporary_insanity_intelligence_check",
        "coc7.characteristic_check",
        "coc7.skill_check",
    ):
        if _procedure_exists(runtime_spec, pid):
            return pid
    return "coc7.characteristic_check"


def _procedure_exists(runtime_spec: dict[str, Any] | None, procedure_id: str) -> bool:
    if not isinstance(runtime_spec, dict):
        return False
    specs = runtime_spec.get("_runtime_check_specs")
    return isinstance(specs, dict) and isinstance(specs.get(procedure_id), dict)


def _followup_result_summary(execution: CheckExecution) -> dict[str, Any]:
    return {
        "procedure_id": execution.trace.procedure_id,
        "skill": execution.args.skill,
        "value": execution.args.value,
        "roll": execution.trace.roll_total,
        "tier": execution.result.tier,
        "passed": execution.result.passed,
        "seed": execution.trace.roll_seed,
    }


def _looks_like_sanity_check(check_log: Any, execution: CheckExecution) -> bool:
    side = execution.result.side_effects or {}
    pid = str(getattr(check_log, "procedure_id", "") or execution.trace.procedure_id or "").lower()
    if "sanity" in pid or pid.endswith(".san_roll") or pid.endswith(".sanity_roll"):
        return True
    skill = str(execution.args.skill or execution.trace.skill or "").strip().lower()
    if skill in {"san", "sanity", "理智", "理智检定"}:
        return True
    return bool(
        pid.startswith("coc")
        and any(k in side for k in ("san_loss", "sanity_loss", "sanity_delta", "san_delta"))
    )


def _sanity_delta_and_loss(execution: CheckExecution) -> tuple[int | None, int]:
    facts = axis_facts(execution)
    for key in ("san_loss", "sanity_loss"):
        value = number(facts.get(key))
        if value is not None:
            loss = max(0, int(value))
            return -loss, loss
    for key in ("sanity_delta", "san_delta"):
        value = number(facts.get(key))
        if value is not None:
            delta = int(value)
            return delta, max(0, -delta)
    return None, 0


def _sanity_before_hint(execution: CheckExecution) -> int | None:
    value = number(execution.args.value)
    if value is not None:
        return int(value)
    axes = execution.result.result_axes or {}
    ir = axes.get("_ir") if isinstance(axes, dict) else None
    runtime_args = ir.get("runtime_args") if isinstance(ir, dict) else None
    if isinstance(runtime_args, dict):
        for key in ("current_sanity", "sanity", "value", "target_value"):
            value = number(runtime_args.get(key))
            if value is not None:
                return int(value)
    return None


def _apply_daily_sanity_counter(
    session: Any,
    *,
    loss: int,
    day_start_hint: Any,
) -> dict[str, Any]:
    module_state = (
        dict(getattr(session, "module_state", None))
        if isinstance(getattr(session, "module_state", None), dict) else {}
    )
    day = str(module_state.get("day_count") or 1)
    counters = module_state.get("rule_consequence_counters")
    if not isinstance(counters, dict):
        counters = {}
    sanity = counters.get("coc7.sanity")
    if not isinstance(sanity, dict) or str(sanity.get("day") or "") != day:
        sanity = {
            "day": day,
            "day_start_sanity": number(day_start_hint),
            "lost_today": 0,
            "triggered_flags": [],
        }
    if sanity.get("day_start_sanity") is None:
        sanity["day_start_sanity"] = number(day_start_hint)
    sanity["lost_today"] = int(sanity.get("lost_today") or 0) + int(loss)
    day_start = number(sanity.get("day_start_sanity")) or 0
    threshold = max(1, math.floor(day_start / 5)) if day_start > 0 else 0
    sanity["indefinite_threshold"] = threshold
    triggered = [str(x) for x in sanity.get("triggered_flags") or []]
    triggered_indefinite = (
        threshold > 0
        and sanity["lost_today"] >= threshold
        and "indefinite_insanity" not in triggered
    )
    if triggered_indefinite:
        triggered.append("indefinite_insanity")
    sanity["triggered_flags"] = triggered
    counters["coc7.sanity"] = sanity
    module_state["rule_consequence_counters"] = counters
    session.module_state = module_state
    safe_flag_modified(session, "module_state")
    return {
        "day": day,
        "day_start_sanity": sanity.get("day_start_sanity"),
        "lost_today": sanity.get("lost_today"),
        "indefinite_threshold": threshold,
        "triggered_indefinite": triggered_indefinite,
    }


def _lookup_int_value(session: Any, actor_id_value: str) -> int | None:
    target, _dirty = actor_root(session, actor_id_value)
    if target is None:
        return None
    for key in ("INT", "int", "智力"):
        value = lookup_named_numeric(target, key)
        if value is not None:
            return int(value)
    return None


def _sanity_path_candidates() -> tuple[str, ...]:
    return (
        "resources.sanity.current",
        "derived_values.sanity.current",
        "derived.sanity.current",
        "sp.current",
        "resources.sp.current",
        "sanity.current",
        "params.resources.sanity.current",
        "params.sanity.current",
        "params.sp.current",
    )
