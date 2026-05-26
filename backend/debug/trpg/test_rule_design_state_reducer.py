"""Reducer tests for backend.agents.rule_editor.design_state.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_state_reducer.py

Covers the documented patch vocabulary (happy paths and error paths),
all-or-nothing rollback semantics, and input-immutability guarantees.
Defaults / validator / summary coverage lives in sibling files.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state import (  # noqa: E402
    DesignPatchError,
    apply_design_ops,
    empty_design_state,
    parse_design_ops,
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
# Reducer: per-op happy paths
# ---------------------------------------------------------------------------


def case_set_phase() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_phase", "phase": "core_loop"},
    ]))
    assert_eq("set_phase value", res.design_state["phase"], "core_loop")
    assert_eq("set_phase diff len", len(res.diff), 1)


def case_set_brief_field_and_assumption() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept", "value": "noir mystery"},
        {"op": "set_brief_field", "field": "tone", "value": "dread"},
        {"op": "add_assumption", "assumption": "Investigators are mortal"},
    ]))
    assert_eq("brief concept", res.design_state["brief"]["concept"], "noir mystery")
    assert_eq("brief tone", res.design_state["brief"]["tone"], "dread")
    assert_eq("brief assumptions", res.design_state["brief"]["assumptions"],
              ["Investigators are mortal"])


def case_set_taxonomy_field() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_taxonomy_field", "field": "genre", "value": "horror"},
        {"op": "set_taxonomy_field", "field": "era", "value": "modern"},
    ]))
    assert_eq("taxonomy genre", res.design_state["taxonomy"]["genre"], "horror")
    assert_eq("taxonomy era", res.design_state["taxonomy"]["era"], "modern")


def case_set_blueprint_seeds_slot_keys() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_blueprint", "blueprint_id": "d20_heroic_adventure",
         "slots_required": ["core_loop", "resolution_model"],
         "taxonomy_overrides": {"genre": "fantasy"}},
    ]))
    bp = res.design_state["blueprint"]
    assert_eq("blueprint id", bp["id"], "d20_heroic_adventure")
    assert_eq("blueprint slots_required", bp["slots_required"],
              ["core_loop", "resolution_model"])
    assert_eq("blueprint taxonomy_overrides",
              bp["taxonomy_overrides"], {"genre": "fantasy"})
    slots = res.design_state["slots"]
    assert_eq("slots seeded missing", slots,
              {"core_loop": "missing", "resolution_model": "missing"})


def case_set_slot_status_updates() -> None:
    state = empty_design_state()
    state["slots"] = {"core_loop": "missing"}
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_slot_status", "slot": "core_loop", "status": "drafting"},
        {"op": "set_slot_status", "slot": "core_loop", "status": "filled"},
    ]))
    assert_eq("slot status final",
              res.design_state["slots"]["core_loop"], "filled")
    assert_eq("slot status diff count", len(res.diff), 2)


def case_set_core_loop_merges_only_provided_fields() -> None:
    state = empty_design_state()
    state["core_loop"]["summary"] = "old summary"
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_core_loop", "summary": "new summary"},
    ]))
    cl = res.design_state["core_loop"]
    assert_eq("core_loop summary new", cl["summary"], "new summary")
    assert_eq("core_loop phases preserved", cl["phases"], [])
    assert_eq("core_loop pacing preserved", cl["pacing"], "")


def case_set_resolution_model_no_fields_rejects() -> None:
    state = empty_design_state()
    try:
        apply_design_ops(state, parse_design_ops([
            {"op": "set_resolution_model"},
        ]))
    except DesignPatchError as e:
        assert_eq("set_resolution_model no_fields code", e.code, "no_fields")
        return
    fail("set_resolution_model no fields", "expected DesignPatchError")


def case_upsert_remove_procedure() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "upsert_procedure", "id": "combat",
         "procedure": {"name": "Combat", "when": "violence", "steps": []}},
        {"op": "upsert_procedure", "id": "stealth",
         "procedure": {"name": "Stealth", "when": "sneaking", "steps": []}},
    ]))
    assert_eq("procedures count", len(res.design_state["procedures"]), 2)
    proc_ids = [p["id"] for p in res.design_state["procedures"]]
    assert_eq("procedure ids", proc_ids, ["combat", "stealth"])

    res2 = apply_design_ops(res.design_state, parse_design_ops([
        {"op": "upsert_procedure", "id": "combat",
         "procedure": {"name": "Combat v2", "when": "violence", "steps": []}},
    ]))
    combat = next(
        p for p in res2.design_state["procedures"] if p["id"] == "combat"
    )
    assert_eq("procedure updated in place", combat["name"], "Combat v2")
    assert_eq("procedures still 2", len(res2.design_state["procedures"]), 2)

    res3 = apply_design_ops(res2.design_state, parse_design_ops([
        {"op": "remove_procedure", "id": "combat"},
    ]))
    assert_eq("procedures after remove", len(res3.design_state["procedures"]), 1)


def case_remove_procedure_unknown_rejects() -> None:
    state = empty_design_state()
    try:
        apply_design_ops(state, parse_design_ops([
            {"op": "remove_procedure", "id": "ghost"},
        ]))
    except DesignPatchError as e:
        assert_eq("remove_procedure not_found", e.code, "not_found")
        return
    fail("remove unknown procedure", "expected DesignPatchError")


def case_upsert_remove_catalog_entry() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "upsert_catalog_entry", "catalog": "skills",
         "id": "lockpick", "entry": {"name": "Lockpick", "default": 25}},
        {"op": "upsert_catalog_entry", "catalog": "skills",
         "id": "stealth", "entry": {"name": "Stealth", "default": 30}},
        {"op": "upsert_catalog_entry", "catalog": "actions",
         "id": "shoot", "entry": {"name": "Shoot"}},
    ]))
    skills = res.design_state["catalogs"]["skills"]
    assert_eq("skills count", len(skills), 2)
    actions = res.design_state["catalogs"]["actions"]
    assert_eq("actions count", len(actions), 1)
    res2 = apply_design_ops(res.design_state, parse_design_ops([
        {"op": "remove_catalog_entry", "catalog": "skills", "id": "lockpick"},
    ]))
    assert_eq("skills after remove",
              len(res2.design_state["catalogs"]["skills"]), 1)


def case_set_compile_status() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_compile_status", "status": "failed",
         "error": "missing core loop"},
    ]))
    cmp_block = res.design_state["compile"]
    assert_eq("compile status", cmp_block["status"], "failed")
    assert_eq("compile error", cmp_block["error"], "missing core loop")


# ---------------------------------------------------------------------------
# Reducer: error paths
# ---------------------------------------------------------------------------


def case_unknown_op_rejects() -> None:
    try:
        parse_design_ops([{"op": "do_a_barrel_roll"}])
    except DesignPatchError as e:
        assert_eq("unknown op code", e.code, "unknown_op")
        return
    fail("unknown op", "expected DesignPatchError")


def case_invalid_args_rejects() -> None:
    try:
        parse_design_ops([
            {"op": "set_phase", "phase": "not_a_phase"},
        ])
    except DesignPatchError as e:
        assert_eq("invalid_args code", e.code, "invalid_args")
        return
    fail("invalid args", "expected DesignPatchError")


def case_set_phase_drafting_rejects() -> None:
    """Regression: `drafting` is a SLOT status, not a PHASE.

    The agent has tried to use `phase: drafting`; the reducer must
    reject it so the error surfaces back to the LLM in the
    all-or-nothing payload.
    """
    try:
        parse_design_ops([
            {"op": "set_phase", "phase": "drafting"},
        ])
    except DesignPatchError as e:
        assert_eq("set_phase drafting code", e.code, "invalid_args")
        return
    fail("set_phase drafting", "expected DesignPatchError")


def case_add_assumption_missing_field_rejects() -> None:
    """Regression: omitting `assumption` must fail validation."""
    try:
        parse_design_ops([
            {"op": "add_assumption"},
        ])
    except DesignPatchError as e:
        assert_eq(
            "add_assumption missing field code", e.code, "invalid_args",
        )
        return
    fail("add_assumption missing field", "expected DesignPatchError")


def case_upsert_catalog_entry_missing_entry_rejects() -> None:
    """Regression: omitting `entry` must fail validation."""
    try:
        parse_design_ops([
            {
                "op": "upsert_catalog_entry",
                "catalog": "skills",
                "id": "spot",
            },
        ])
    except DesignPatchError as e:
        assert_eq(
            "upsert_catalog_entry missing entry code",
            e.code, "invalid_args",
        )
        return
    fail("upsert_catalog_entry missing entry", "expected DesignPatchError")


def case_bad_id_rejects() -> None:
    state = empty_design_state()
    try:
        apply_design_ops(state, parse_design_ops([
            {"op": "upsert_procedure", "id": "../etc",
             "procedure": {"name": "x"}},
        ]))
    except DesignPatchError as e:
        assert_eq("bad_id code", e.code, "bad_id")
        return
    fail("bad id", "expected DesignPatchError")


def case_all_or_nothing_rollback() -> None:
    state = empty_design_state()
    state["phase"] = "intake"
    snapshot = copy.deepcopy(state)
    try:
        apply_design_ops(state, parse_design_ops([
            {"op": "set_phase", "phase": "core_loop"},
            {"op": "remove_procedure", "id": "ghost"},  # invalid
            {"op": "set_phase", "phase": "ready"},
        ]))
    except DesignPatchError as e:
        assert_eq("rollback offending op_index", e.op_index, 1)
        assert_eq("rollback source untouched", state, snapshot)
        return
    fail("all-or-nothing rollback", "expected DesignPatchError")


def case_input_not_mutated() -> None:
    state = empty_design_state()
    snapshot = copy.deepcopy(state)
    apply_design_ops(state, parse_design_ops([
        {"op": "set_phase", "phase": "core_loop"},
        {"op": "set_brief_field", "field": "concept", "value": "x"},
        {"op": "upsert_procedure", "id": "p1", "procedure": {"name": "P1"}},
    ]))
    assert_eq("input dict deep-equal to snapshot", state, snapshot)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    case_set_phase()
    case_set_brief_field_and_assumption()
    case_set_taxonomy_field()
    case_set_blueprint_seeds_slot_keys()
    case_set_slot_status_updates()
    case_set_core_loop_merges_only_provided_fields()
    case_set_resolution_model_no_fields_rejects()
    case_upsert_remove_procedure()
    case_remove_procedure_unknown_rejects()
    case_upsert_remove_catalog_entry()
    case_set_compile_status()
    case_unknown_op_rejects()
    case_invalid_args_rejects()
    case_set_phase_drafting_rejects()
    case_add_assumption_missing_field_rejects()
    case_upsert_catalog_entry_missing_entry_rejects()
    case_bad_id_rejects()
    case_all_or_nothing_rollback()
    case_input_not_mutated()
    print("\nAll design_state reducer tests passed.")


if __name__ == "__main__":
    main()
