"""Summary tests for backend.agents.rule_editor.design_state.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_state_summary.py

Covers the compact summary builder used by the agent prompt and the
frontend design panel. Defaults / reducer / validator coverage lives in
sibling files.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state import (  # noqa: E402
    apply_design_ops,
    build_summary,
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
# Summary
# ---------------------------------------------------------------------------


def case_summary_compact_view() -> None:
    state = empty_design_state()
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept",
         "value": "modern paranormal"},
        {"op": "set_phase", "phase": "core_loop"},
        {"op": "set_blueprint", "blueprint_id": "demo_bp",
         "slots_required": ["core_loop"]},
        {"op": "set_core_loop", "summary": "scene -> action -> roll"},
        {"op": "set_slot_status", "slot": "core_loop", "status": "filled"},
        {"op": "upsert_catalog_entry", "catalog": "skills",
         "id": "lock", "entry": {"name": "Lock"}},
        {"op": "upsert_catalog_entry", "catalog": "skills",
         "id": "stealth", "entry": {"name": "Stealth"}},
    ]))
    summary = build_summary(res.design_state)
    assert_eq("summary phase", summary["phase"], "core_loop")
    assert_eq("summary brief concept_preview",
              summary["brief"]["concept_preview"], "modern paranormal")
    assert_eq("summary blueprint id",
              summary["blueprint"]["id"], "demo_bp")
    assert_eq("summary slot progress",
              summary["slots"]["progress"], 1.0)
    assert_eq("summary core_loop_filled",
              summary["sections"]["core_loop_filled"], True)
    assert_eq("summary skills catalog count",
              summary["sections"]["catalog_counts"]["skills"], 2)


def case_summary_truncates_long_concept() -> None:
    state = empty_design_state()
    long_text = "x" * 500
    res = apply_design_ops(state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept", "value": long_text},
    ]))
    summary = build_summary(res.design_state)
    preview = summary["brief"]["concept_preview"]
    assert_true(
        "preview shorter than original",
        len(preview) < len(long_text),
    )
    assert_true(
        "preview ends with ellipsis",
        preview.endswith("..."),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    case_summary_compact_view()
    case_summary_truncates_long_concept()
    print("\nAll design_state summary tests passed.")


if __name__ == "__main__":
    main()
