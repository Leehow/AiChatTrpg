"""Pure-only smokes for the P0.6 main rule-editor agent integration.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_agent_p0_6_schema.py

Covers (no DB, no LLM):

1. Phase-aware tool schema hides every legacy parsed_v6 writer and
   exposes the design-state + blueprint + compile_design surface.
2. System prompt is design-state-first (no "DO NOT design dice"
   prohibition; mentions design_state + compile_design + apply_blueprint).
3. Event helper: design-state write payload yields the
   `design_state_changed` + `validation_report` SSE pair, and the
   `_design_state_changed` marker is stripped from the public payload.

DB-backed service smokes live in
`test_rule_design_agent_p0_6_service.py` so each file stays under the
400-line cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.agent_context import (  # noqa: E402
    events_from_tool_payload,
    strip_internal_markers,
)
from agents.rule_editor.design_state.defaults import (  # noqa: E402
    CATALOG_NAMES,
    PHASES,
    SLOT_STATUSES,
)
from agents.rule_editor.prompts import (  # noqa: E402
    build_system_prompt,
    render_design_context,
)
from agents.rule_editor.tools import (  # noqa: E402
    P0_6_HIDDEN_NAMES,
    allowed_tool_names_for_draft,
    build_tools_schema_for_draft,
    get_allowed_tool_for_draft,
)


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def assert_eq(label, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}\n  expected: {expected!r}\n  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


# ---------------------------------------------------------------------------
# 1. Phase-aware tool schema gating
# ---------------------------------------------------------------------------


def test_phase_aware_schema() -> None:
    print("\n--- 1. phase-aware tool schema ---")
    schema = build_tools_schema_for_draft(draft=None)
    assert_true("schema: returned a list", isinstance(schema, list))
    advertised = {entry["function"]["name"] for entry in schema}

    must_advertise = {
        "read_draft",
        "read_design_state",
        "validate_design_state",
        "list_blueprints",
        "recommend_blueprints",
        "apply_blueprint",
        "apply_design_ops",
        "compile_design",
    }
    missing = must_advertise - advertised
    assert_true(
        "schema: required design-state surface advertised",
        not missing, why=f"missing={sorted(missing)}",
    )

    leaks = advertised & set(P0_6_HIDDEN_NAMES)
    assert_true(
        "schema: legacy parsed_v6 writers hidden",
        not leaks, why=f"leaked={sorted(leaks)}",
    )

    for hidden in P0_6_HIDDEN_NAMES:
        if get_allowed_tool_for_draft(None, hidden) is not None:
            fail(
                "schema: hidden tool resolved through gated lookup",
                why=hidden,
            )
    assert_true(
        "schema: hidden tools rejected via gated lookup",
        get_allowed_tool_for_draft(None, "design_core_rules") is None,
    )
    assert_true(
        "schema: design-state tool resolves via gated lookup",
        get_allowed_tool_for_draft(None, "apply_design_ops") is not None,
    )
    assert_true(
        "schema: allowed names cover schema",
        set(allowed_tool_names_for_draft(None)) == advertised,
    )


# ---------------------------------------------------------------------------
# 1b. apply_design_ops oneOf op-shape schema
# ---------------------------------------------------------------------------


def _apply_design_ops_params() -> dict:
    schema = build_tools_schema_for_draft(draft=None)
    entry = next(
        e for e in schema if e["function"]["name"] == "apply_design_ops"
    )
    return entry["function"]["parameters"]


def _branches_by_op() -> dict[str, dict]:
    items = _apply_design_ops_params()["properties"]["ops"]["items"]
    out: dict[str, dict] = {}
    for br in items.get("oneOf") or []:
        op_const = br.get("properties", {}).get("op", {}).get("const")
        if isinstance(op_const, str):
            out[op_const] = br
    return out


def _req(branch: dict) -> list[str]:
    return sorted(branch.get("required") or [])


def test_apply_design_ops_op_schema() -> None:
    print("\n--- 1b. apply_design_ops op-shape schema ---")
    branches = _branches_by_op()
    expected_ops = {
        "set_phase", "set_brief_field", "add_assumption",
        "set_taxonomy_field", "set_blueprint", "set_slot_status",
        "set_core_loop", "set_character_model", "set_resolution_model",
        "upsert_procedure", "remove_procedure", "upsert_catalog_entry",
        "remove_catalog_entry", "set_compile_status",
    }
    assert_true(
        "ops schema: every documented op has a oneOf branch",
        set(branches.keys()) == expected_ops,
        why=f"got={sorted(branches.keys())}",
    )
    sp = branches["set_phase"]
    phase_enum = sp["properties"]["phase"].get("enum") or []
    assert_eq("set_phase enum == PHASES", list(phase_enum), list(PHASES))
    assert_true(
        "set_phase rejects `drafting`", "drafting" not in phase_enum,
    )
    assert_eq("set_phase required", _req(sp), ["op", "phase"])
    aa = branches["add_assumption"]
    assert_eq(
        "add_assumption required = [assumption, op]",
        _req(aa), ["assumption", "op"],
    )
    assert_true(
        "add_assumption: only op+assumption, closed",
        set(aa["properties"].keys()) == {"op", "assumption"}
        and aa.get("additionalProperties") is False,
    )
    uc = branches["upsert_catalog_entry"]
    assert_eq(
        "upsert_catalog_entry required",
        _req(uc), ["catalog", "entry", "id", "op"],
    )
    assert_eq(
        "upsert_catalog_entry catalog enum",
        list(uc["properties"]["catalog"].get("enum") or []),
        list(CATALOG_NAMES),
    )
    assert_eq(
        "upsert_catalog_entry.entry is object",
        uc["properties"]["entry"].get("type"), "object",
    )
    ss = branches["set_slot_status"]
    assert_eq(
        "set_slot_status status enum",
        list(ss["properties"]["status"].get("enum") or []),
        list(SLOT_STATUSES),
    )
    assert_eq(
        "set_slot_status required", _req(ss), ["op", "slot", "status"],
    )
    assert_eq(
        "upsert_procedure required",
        _req(branches["upsert_procedure"]), ["id", "op", "procedure"],
    )
    assert_true(
        "set_blueprint requires blueprint_id",
        "blueprint_id" in _req(branches["set_blueprint"]),
    )
    ops_field = _apply_design_ops_params()["properties"]["ops"]
    assert_eq("ops array minItems=1", ops_field.get("minItems"), 1)


# ---------------------------------------------------------------------------
# 2. System prompt content
# ---------------------------------------------------------------------------


def test_prompt_content() -> None:
    print("\n--- 2. system prompt content ---")
    prompt = build_system_prompt()
    forbidden_phrases = [
        "DO NOT design",
        "Dice rules are authored separately",
    ]
    for phrase in forbidden_phrases:
        if phrase in prompt:
            fail(f"prompt: stale prohibition `{phrase!r}` present")
    print("OK: prompt has no stale dice/parsed_v6 prohibitions")

    must_mention = [
        "design_state",
        "apply_design_ops",
        "compile_design",
        "apply_blueprint",
        "set_resolution_model",
        # Op-shape cheat sheet additions (P0.8 schema repair).
        "cheat sheet",
        "There is no `drafting` phase",
        "required key is `assumption`",
        "required keys are `catalog`, `id`, AND",
        "Filling required slots",
    ]
    for phrase in must_mention:
        assert_true(
            f"prompt: mentions `{phrase}`",
            phrase in prompt,
        )

    block = render_design_context(
        design_phase="intake",
        design_summary={
            "phase": "intake",
            "brief": {
                "concept_preview": "ghost-hunters",
                "tone": "tense",
                "genre": "horror",
                "assumption_count": 1,
            },
            "blueprint": {"id": "", "slots_required_count": 0},
            "slots": {
                "required": ["combat"], "filled": [], "missing": ["combat"],
                "drafting": [], "progress": 0.0,
            },
            "sections": {
                "core_loop_filled": False,
                "resolution_mechanic_filled": False,
                "character_attribute_count": 0,
                "procedure_count": 0,
                "catalog_counts": {
                    "skills": 0, "actions": 0, "resources": 0, "gear": 0,
                },
            },
            "issues": {
                "blocking_count": 2, "warning_count": 0, "info_count": 0,
                "ready_blockers": ["blueprint_required", "slot_missing"],
                "first_blocking": {
                    "code": "blueprint_required",
                    "message": "No blueprint selected -- required for compile.",
                },
            },
            "compile": {"status": "idle", "has_error": False},
            "can_compile": False,
        },
        validation_report={
            "can_compile": False,
            "ready_blockers": ["blueprint_required", "slot_missing"],
        },
        allowed_tool_names=["read_draft", "apply_design_ops"],
    )
    assert_true(
        "context block: includes phase line",
        "phase: intake" in block,
    )
    assert_true(
        "context block: lists tools_available",
        "tools_available:" in block and "apply_design_ops" in block,
    )
    assert_true(
        "context block: surfaces ready_blockers",
        "blueprint_required" in block,
    )

    full_prompt = build_system_prompt(context_block=block)
    assert_true(
        "build_system_prompt: appends context block",
        "Current design state" in full_prompt
        and "design_state" in full_prompt,
    )


# ---------------------------------------------------------------------------
# 3. Event helper
# ---------------------------------------------------------------------------


def test_event_helper() -> None:
    print("\n--- 3. event helper ---")
    payload = {
        "ok": True,
        "design_phase": "core_loop",
        "design_summary": {"phase": "core_loop"},
        "validation_report": {"can_compile": False, "ready_blockers": ["x"]},
        "can_compile": False,
        "edit_id": "edit_abc",
        "diff": [{"path": ["phase"], "before": "intake", "after": "core_loop"}],
        "_design_state_changed": True,
    }
    events = events_from_tool_payload(payload=payload, edit_id="edit_abc")
    assert_eq("event count", len(events), 2)
    assert_eq(
        "first event type", events[0]["type"], "design_state_changed",
    )
    assert_eq(
        "first event phase", events[0]["design_phase"], "core_loop",
    )
    assert_eq(
        "first event edit_id", events[0]["edit_id"], "edit_abc",
    )
    assert_true(
        "first event diff carried",
        isinstance(events[0]["diff"], list) and bool(events[0]["diff"]),
    )
    assert_eq(
        "second event type", events[1]["type"], "validation_report",
    )
    assert_eq(
        "second event can_compile", events[1]["can_compile"], False,
    )

    public = strip_internal_markers(payload)
    assert_true(
        "public payload: marker stripped",
        "_design_state_changed" not in public,
    )
    assert_true(
        "public payload: keeps validation_report",
        "validation_report" in public,
    )

    ro_payload = {
        "ok": True,
        "design_phase": "intake",
        "validation_report": {"can_compile": True, "ready_blockers": []},
        "can_compile": True,
    }
    ro_events = events_from_tool_payload(payload=ro_payload, edit_id=None)
    assert_eq("read-only: event count", len(ro_events), 1)
    assert_eq(
        "read-only: only validation_report",
        ro_events[0]["type"], "validation_report",
    )
    assert_eq(
        "read-only: can_compile mirrored",
        ro_events[0]["can_compile"], True,
    )

    # Empty / missing markers -> no events at all.
    no_events = events_from_tool_payload(
        payload={"ok": True}, edit_id=None,
    )
    assert_eq("empty payload: 0 events", len(no_events), 0)


def main() -> None:
    test_phase_aware_schema()
    test_apply_design_ops_op_schema()
    test_prompt_content()
    test_event_helper()
    print("\nAll P0.6 schema/prompt/event smokes passed.")


if __name__ == "__main__":
    main()
