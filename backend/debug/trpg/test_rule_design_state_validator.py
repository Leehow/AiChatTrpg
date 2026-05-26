"""Validator tests for backend.agents.rule_editor.design_state.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_state_validator.py

Covers blocking / warning issue codes, slot completion, can_compile and
ready_blockers behavior. Defaults / reducer / summary coverage lives in
sibling files.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state import (  # noqa: E402
    apply_design_ops,
    empty_design_state,
    parse_design_ops,
    validate_design_state,
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
# Validator
# ---------------------------------------------------------------------------


def case_validator_empty_state_blocks_compile() -> None:
    state = empty_design_state()
    report = validate_design_state(state)
    assert_true("empty state cannot compile", not report.can_compile)
    codes = {iss.code for iss in report.blocking}
    assert_true(
        "blueprint_required is blocking",
        "blueprint_required" in codes,
    )
    assert_true(
        "core_loop_summary_missing is blocking",
        "core_loop_summary_missing" in codes,
    )
    assert_true(
        "resolution_mechanic_missing is blocking",
        "resolution_mechanic_missing" in codes,
    )


def case_validator_required_slots_count_as_blocking() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_blueprint", "blueprint_id": "x_test",
         "slots_required": ["core_loop", "resolution_model"]},
        {"op": "set_core_loop", "summary": "play loop"},
        {"op": "set_resolution_model", "mechanic": "d20"},
    ]))
    report = validate_design_state(res.design_state)
    codes = [iss.code for iss in report.blocking]
    assert_eq(
        "exactly two slot_missing entries",
        codes.count("slot_missing"), 2,
    )
    assert_eq(
        "slots progress 0",
        report.slots.progress, 0.0,
    )


def case_validator_can_compile_when_required_filled() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept", "value": "test"},
        {"op": "set_blueprint", "blueprint_id": "x_test",
         "slots_required": ["core_loop"]},
        {"op": "set_slot_status", "slot": "core_loop", "status": "filled"},
        {"op": "set_core_loop", "summary": "scene -> action -> roll"},
        {"op": "set_resolution_model", "mechanic": "d100 roll-under",
         "dice": "1d100"},
        {"op": "set_character_model",
         "attributes": [{"id": "str", "name": "Strength"}]},
    ]))
    report = validate_design_state(res.design_state)
    assert_true("can_compile true", report.can_compile)
    assert_eq("ready_blockers empty", report.ready_blockers, [])
    assert_eq(
        "all required slots filled",
        sorted(report.slots.filled), ["core_loop"],
    )
    assert_eq("progress 1.0", report.slots.progress, 1.0)


def case_validator_warnings_do_not_block_compile() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept", "value": "x"},
        {"op": "set_blueprint", "blueprint_id": "x_test", "slots_required": []},
        {"op": "set_core_loop", "summary": "loop"},
        {"op": "set_resolution_model", "mechanic": "d100 roll-under"},
        {"op": "set_character_model",
         "attributes": [{"id": "x", "name": "X"}]},
    ]))
    report = validate_design_state(res.design_state)
    assert_true("can_compile despite warnings", report.can_compile)
    warning_codes = {iss.code for iss in report.warnings}
    assert_true(
        "resolution_dice_missing is a warning",
        "resolution_dice_missing" in warning_codes,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    case_validator_empty_state_blocks_compile()
    case_validator_required_slots_count_as_blocking()
    case_validator_can_compile_when_required_filled()
    case_validator_warnings_do_not_block_compile()
    print("\nAll design_state validator tests passed.")


if __name__ == "__main__":
    main()
