"""Persistence helpers for replayable TRPG CHECK logs."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from agents.trpg.check_runtime import CheckExecution
from orm.models import CheckLog, GameSession
from services.trpg_rule_consequences import (
    RULE_CONSEQUENCE_FOLLOWUP_SOURCE,
    apply_rule_consequences,
    attach_consequences_to_payloads,
)


def record_check_execution(
    db: Any,
    session: GameSession,
    execution: CheckExecution,
    *,
    message_id: str | None = None,
    actor_id: str = "",
    source: str = "",
    request_json: dict[str, Any] | None = None,
    result_json: dict[str, Any] | None = None,
    append_history: bool = True,
    log_id: str | None = None,
    runtime_spec: dict[str, Any] | None = None,
    apply_consequences: bool = True,
) -> CheckLog:
    """Add a CheckLog row and optionally mirror it into session.dice_history."""

    trace = execution.trace.to_metadata()
    request = copy.deepcopy(request_json) if isinstance(request_json, dict) else _request_payload(execution)
    result = copy.deepcopy(result_json) if isinstance(result_json, dict) else _result_payload(execution)
    resolved_source = str(source or trace.get("source") or "").strip()
    resolved_actor = str(actor_id or _actor_id_from_execution(execution) or "").strip()
    created_at = datetime.now(timezone.utc)
    check_log = CheckLog(
        id=log_id or str(uuid.uuid4()),
        session_id=str(session.id),
        message_id=message_id,
        actor_id=resolved_actor,
        procedure_id=str(trace.get("procedure_id") or ""),
        engine=str(trace.get("engine") or execution.result.engine or ""),
        skill=str(execution.args.skill or ""),
        seed=str(trace.get("roll_seed") or ""),
        source=resolved_source,
        request_json=request,
        result_json=result,
        roll_trace_json=copy.deepcopy(trace.get("roll_trace") or {}),
        trace_json=copy.deepcopy(trace),
        warnings_json=[str(w) for w in trace.get("warnings") or [] if str(w)],
        created_at=created_at,
        updated_at=created_at,
    )
    consequence_result = None
    if apply_consequences:
        consequence_result = apply_rule_consequences(
            session,
            check_log,
            execution,
            runtime_spec=runtime_spec,
            allow_followup=resolved_source != RULE_CONSEQUENCE_FOLLOWUP_SOURCE,
        )
        attach_consequences_to_payloads(
            check_log,
            consequence_result.consequences,
        )
    db.add(check_log)
    if append_history:
        append_check_history(
            session,
            check_log,
            execution,
            check_log.request_json or request,
            check_log.result_json or result,
        )
    if consequence_result is not None:
        for followup_execution in consequence_result.followup_executions:
            record_check_execution(
                db,
                session,
                followup_execution,
                message_id=message_id,
                actor_id=resolved_actor,
                source=RULE_CONSEQUENCE_FOLLOWUP_SOURCE,
                append_history=append_history,
                runtime_spec=runtime_spec,
                apply_consequences=False,
            )
    return check_log


def append_check_history(
    session: GameSession,
    check_log: CheckLog,
    execution: CheckExecution,
    request_json: dict[str, Any],
    result_json: dict[str, Any],
) -> dict[str, Any]:
    """Append the compact legacy dice_history mirror for one CheckLog."""

    trace = copy.deepcopy(check_log.trace_json or {})
    entry = {
        "check_log_id": check_log.id,
        "message_id": check_log.message_id,
        "expression": trace.get("roll_expression") or check_log.engine,
        "engine": check_log.engine,
        "procedure_id": check_log.procedure_id,
        "actor_id": check_log.actor_id,
        "result": trace.get("roll_total"),
        "request": copy.deepcopy(request_json),
        "result_detail": copy.deepcopy(result_json),
        "warnings": list(check_log.warnings_json or []),
        "skill": execution.args.skill,
        "value": execution.args.value,
        "difficulty": execution.args.difficulty,
        "reason": execution.args.reason,
        "time": check_log.created_at.isoformat(),
        "source": check_log.source,
        "seed": check_log.seed,
        "roll_trace": copy.deepcopy(check_log.roll_trace_json or {}),
        "trace": trace,
    }
    history = list(session.dice_history or [])
    if isinstance(check_log.result_json, dict) and check_log.result_json.get("rule_consequences"):
        entry["rule_consequences"] = copy.deepcopy(check_log.result_json["rule_consequences"])
    history.append(entry)
    session.dice_history = history
    flag_modified(session, "dice_history")
    return entry


def _request_payload(execution: CheckExecution) -> dict[str, Any]:
    args = execution.args
    extras = copy.deepcopy(args.extras or {})
    return {
        "procedure_id": str(execution.trace.procedure_id or extras.get("procedure_id") or ""),
        "requested_procedure_id": str(execution.trace.requested_procedure_id or ""),
        "skill": args.skill,
        "value": args.value,
        "roll": args.roll,
        "difficulty": args.difficulty,
        "bonus": args.bonus,
        "penalty": args.penalty,
        "pool": args.pool,
        "target": args.target,
        "reason": args.reason,
        "extras": extras,
    }


def _result_payload(execution: CheckExecution) -> dict[str, Any]:
    result = execution.result
    return {
        "tier": result.tier,
        "tier_label": result.tier_label,
        "passed": result.passed,
        "explanation": result.explanation,
        "thresholds": copy.deepcopy(result.thresholds or {}),
        "warnings": list(result.warnings or []),
        "engine": result.engine,
        "roll_display": result.roll_display,
        "side_effects": copy.deepcopy(result.side_effects or {}),
        "result_axes": copy.deepcopy(result.result_axes or {}),
    }


def _actor_id_from_execution(execution: CheckExecution) -> str:
    extras = execution.args.extras or {}
    for key in ("actor_id", "actor", "npc_key"):
        value = extras.get(key)
        if value not in (None, ""):
            return str(value)
    actor_lookup = extras.get("actor_lookup")
    if isinstance(actor_lookup, dict):
        actor = actor_lookup.get("actor") or actor_lookup.get("source")
        if actor not in (None, ""):
            return str(actor)
    return ""
