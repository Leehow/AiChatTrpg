"""Deterministic rule consequences for CHECK results.

Dice IR resolves the check itself. This module consumes the structured
``side_effects`` / ``result_axes`` produced by that resolution and applies
rule-level consequences: resource deltas, threshold flags, mandatory follow-up
checks, and prompt-visible narration events.

The implementation is split across same-prefix helper modules:

- ``trpg_rule_consequences_resource`` — actor/resource lookup and primitives.
- ``trpg_rule_consequences_catalog`` — catalog-driven consequence engine.
- ``trpg_rule_consequences_sanity`` — CoC 7e sanity-specific rules.

Public surface stays here so existing imports from
``services.trpg_rule_consequences`` keep working.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from agents.trpg.check_runtime import CheckExecution

from services.trpg_rule_consequences_catalog import apply_catalog_consequences
from services.trpg_rule_consequences_sanity import (
    RULE_CONSEQUENCE_FOLLOWUP_SOURCE,
    apply_coc_sanity_consequence,
)


__all__ = [
    "RULE_CONSEQUENCE_FOLLOWUP_SOURCE",
    "RuleConsequenceApplyResult",
    "apply_rule_consequences",
    "recent_rule_consequences_prompt_block",
    "attach_consequences_to_payloads",
]


@dataclass
class RuleConsequenceApplyResult:
    consequences: list[dict[str, Any]] = field(default_factory=list)
    followup_executions: list[CheckExecution] = field(default_factory=list)


def apply_rule_consequences(
    session: Any,
    check_log: Any,
    execution: CheckExecution,
    *,
    runtime_spec: dict[str, Any] | None = None,
    allow_followup: bool = True,
) -> RuleConsequenceApplyResult:
    """Apply resource/state consequences for one recorded CHECK.

    This function is intentionally synchronous because CHECK recording is
    synchronous. It mutates JSON fields on ``session`` only; callers own DB
    flush/commit.
    """

    source = str(getattr(check_log, "source", "") or execution.trace.source or "")
    if source == RULE_CONSEQUENCE_FOLLOWUP_SOURCE:
        allow_followup = False

    result = RuleConsequenceApplyResult()
    result.consequences.extend(
        apply_catalog_consequences(
            session,
            check_log,
            execution,
            runtime_spec=runtime_spec,
        )
    )
    sanity_events, sanity_followups = apply_coc_sanity_consequence(
        session,
        check_log,
        execution,
        runtime_spec=runtime_spec,
        allow_followup=allow_followup,
    )
    result.consequences.extend(sanity_events)
    result.followup_executions.extend(sanity_followups)
    return result


def recent_rule_consequences_prompt_block(
    session: Any,
    *,
    limit: int = 5,
) -> str:
    """Render recent consequence events for BP3 prompt injection."""

    events: list[dict[str, Any]] = []
    history = getattr(session, "dice_history", None)
    if not isinstance(history, list):
        return ""
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        for event in _entry_consequences(entry):
            if not isinstance(event, dict):
                continue
            contract = event.get("narration_contract")
            if isinstance(contract, dict) and contract.get("llm_may_narrate") is False:
                continue
            events.append(_prompt_safe_event(event))
            if len(events) >= limit:
                break
        if len(events) >= limit:
            break
    if not events:
        return ""
    return (
        "## Recent Rule Consequences\n"
        "These are deterministic rule results already applied by the engine. "
        "Use them for narration, and do not recompute or override the rules.\n"
        "```json\n"
        f"{json.dumps(list(reversed(events)), ensure_ascii=False, indent=2)}\n"
        "```"
    )


def attach_consequences_to_payloads(
    check_log: Any,
    consequences: list[dict[str, Any]],
) -> None:
    """Mirror consequences into CheckLog JSON payloads before history append."""

    if not consequences:
        return
    result_json = dict(getattr(check_log, "result_json", None) or {})
    trace_json = dict(getattr(check_log, "trace_json", None) or {})
    result_json["rule_consequences"] = copy.deepcopy(consequences)
    trace_json["rule_consequences"] = copy.deepcopy(consequences)
    check_log.result_json = result_json
    check_log.trace_json = trace_json


def _entry_consequences(entry: dict[str, Any]) -> list[dict[str, Any]]:
    direct = entry.get("rule_consequences")
    if isinstance(direct, list):
        return [e for e in direct if isinstance(e, dict)]
    detail = entry.get("result_detail")
    if isinstance(detail, dict) and isinstance(detail.get("rule_consequences"), list):
        return [e for e in detail["rule_consequences"] if isinstance(e, dict)]
    trace = entry.get("trace")
    if isinstance(trace, dict) and isinstance(trace.get("rule_consequences"), list):
        return [e for e in trace["rule_consequences"] if isinstance(e, dict)]
    return []


def _prompt_safe_event(event: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "type",
        "system_id",
        "actor_id",
        "procedure_id",
        "resource_changes",
        "flags",
        "followup_checks",
        "insanity",
        "narration_contract",
    }
    return {k: copy.deepcopy(v) for k, v in event.items() if k in keep}
