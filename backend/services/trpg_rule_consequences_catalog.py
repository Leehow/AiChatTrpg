"""Catalog-driven rule-consequence engine.

Reads ``consequences`` lists out of the runtime spec / IR / consequence
catalog, evaluates ``when`` clauses against the structured axis facts of a
``CheckExecution``, and emits prompt-visible consequence events with any
applied resource deltas.

Sanity-specific behavior lives in ``trpg_rule_consequences_sanity``; this
module only handles the generic catalog path.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from agents.trpg.check_runtime import CheckExecution

from services.trpg_rule_consequences_resource import (
    apply_resource_delta,
    generic_resource_paths,
    number,
    string_list,
    system_id_from_procedure,
)


def apply_catalog_consequences(
    session: Any,
    check_log: Any,
    execution: CheckExecution,
    *,
    runtime_spec: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    facts = axis_facts(execution)
    for item in catalog_items(execution.spec, runtime_spec, execution.trace.procedure_id):
        if not isinstance(item, dict):
            continue
        when = item.get("when")
        if isinstance(when, dict) and not when_matches(when, facts):
            continue
        if when is None and not item.get("always"):
            continue

        actor = actor_id(check_log, execution)
        resource_changes: list[dict[str, Any]] = []
        resource_decl = item.get("resource_delta")
        if isinstance(resource_decl, dict):
            axis = str(
                resource_decl.get("axis")
                or resource_decl.get("from")
                or resource_decl.get("id")
                or ""
            )
            delta = number(facts.get(axis))
            if delta is not None:
                resource = str(resource_decl.get("resource") or axis or "resource")
                before_hint = number(resource_decl.get("before"))
                paths = string_list(resource_decl.get("path_candidates"))
                change = apply_resource_delta(
                    session,
                    actor,
                    resource=resource,
                    delta=delta,
                    before_hint=before_hint,
                    path_candidates=paths or generic_resource_paths(resource),
                    clamp_min=resource_decl.get("clamp_min"),
                )
                if change:
                    resource_changes.append(change)

        event = {
            "id": f"{getattr(check_log, 'id', '') or uuid.uuid4().hex}:{item.get('id') or 'consequence'}",
            "type": str(item.get("event_type") or "rule_consequence"),
            "system_id": str(item.get("system_id") or system_id_from_procedure(execution.trace.procedure_id)),
            "actor_id": actor or "pc",
            "source_check_log_id": str(getattr(check_log, "id", "") or ""),
            "procedure_id": str(getattr(check_log, "procedure_id", "") or execution.trace.procedure_id),
            "resource_changes": resource_changes,
            "flags": [str(item.get("id") or "triggered")],
            "narration_contract": {
                "llm_may_narrate": True,
                "llm_must_not_recompute_rules": True,
            },
        }
        if isinstance(item.get("narration_contract"), dict):
            event["narration_contract"].update(item["narration_contract"])
        events.append(event)
    return events


def catalog_items(
    spec: dict[str, Any] | None,
    runtime_spec: dict[str, Any] | None,
    procedure_id: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (spec, runtime_spec):
        if not isinstance(source, dict):
            continue
        for item in consequence_list(source.get("consequences")):
            sig = catalog_item_signature(item)
            if sig in seen:
                continue
            seen.add(sig)
            items.append(item)
        ir = source.get("ir")
        if isinstance(ir, dict):
            for item in consequence_list(ir.get("consequences")):
                sig = catalog_item_signature(item)
                if sig in seen:
                    continue
                seen.add(sig)
                items.append(item)
        catalog = source.get("_runtime_consequence_catalog")
        if isinstance(catalog, dict):
            for item in [
                *consequence_list(catalog.get(procedure_id)),
                *consequence_list(catalog.get("*")),
            ]:
                sig = catalog_item_signature(item)
                if sig in seen:
                    continue
                seen.add(sig)
                items.append(item)
    return items


def catalog_item_signature(item: dict[str, Any]) -> str:
    try:
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(id(item))


def consequence_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        raw_items = raw.get("consequences")
        if isinstance(raw_items, list):
            return [item for item in raw_items if isinstance(item, dict)]
    return []


def axis_facts(execution: CheckExecution) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "tier": execution.result.tier,
        "passed": execution.result.passed,
        "procedure_id": execution.trace.procedure_id,
    }
    facts.update(execution.result.side_effects or {})
    axes = execution.result.result_axes or {}
    if isinstance(axes, dict):
        for key, value in axes.items():
            if isinstance(value, dict):
                if "value" in value:
                    facts[key] = value.get("value")
                elif "delta" in value:
                    facts[key] = value.get("delta")
                elif "tier" in value:
                    facts[key] = value.get("tier")
            else:
                facts[key] = value
    return facts


def when_matches(when: Mapping[str, Any], facts: Mapping[str, Any]) -> bool:
    if "all" in when:
        raw = when.get("all")
        return isinstance(raw, list) and all(
            isinstance(item, dict) and when_matches(item, facts)
            for item in raw
        )
    if "any" in when:
        raw = when.get("any")
        return isinstance(raw, list) and any(
            isinstance(item, dict) and when_matches(item, facts)
            for item in raw
        )
    if "not" in when:
        raw = when.get("not")
        return isinstance(raw, dict) and not when_matches(raw, facts)
    axis = str(when.get("axis") or when.get("var") or "").strip()
    value = facts.get(axis)
    if "eq" in when:
        return value == when.get("eq")
    if "ne" in when:
        return value != when.get("ne")
    numeric = number(value)
    if numeric is None:
        return False
    for op, fn in (
        ("gte", lambda a, b: a >= b),
        ("gt", lambda a, b: a > b),
        ("lte", lambda a, b: a <= b),
        ("lt", lambda a, b: a < b),
    ):
        if op in when:
            rhs = number(when.get(op))
            return rhs is not None and fn(numeric, rhs)
    return bool(value)


def actor_id(check_log: Any, execution: CheckExecution) -> str:
    actor = str(getattr(check_log, "actor_id", "") or "").strip()
    if actor:
        return actor
    extras = execution.args.extras or {}
    for key in ("actor", "actor_id", "npc_key"):
        value = extras.get(key)
        if value not in (None, ""):
            return str(value)
    lookup = extras.get("actor_lookup")
    if isinstance(lookup, dict):
        value = lookup.get("actor") or lookup.get("source")
        if value not in (None, ""):
            return str(value)
    return "pc"
