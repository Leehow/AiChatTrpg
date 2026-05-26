"""Default-shape tests for backend.agents.rule_editor.design_state.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_state.py

This file owns the empty-state shape contract only. Reducer, validator,
and summary coverage live in sibling files:

- test_rule_design_state_reducer.py
- test_rule_design_state_validator.py
- test_rule_design_state_summary.py

Splitting was driven by the 400-line ceiling in CLAUDE.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state import empty_design_state  # noqa: E402


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
# Defaults
# ---------------------------------------------------------------------------


def case_default_state_has_required_sections() -> None:
    state = empty_design_state()
    required = (
        "schema_version", "phase", "brief", "taxonomy", "blueprint",
        "slots", "core_loop", "character_model", "resolution_model",
        "procedures", "catalogs", "action_templates", "playtests",
        "compile",
    )
    for key in required:
        assert_true(f"default has section {key}", key in state)
    assert_eq("default schema_version", state["schema_version"], 1)
    assert_eq("default phase", state["phase"], "intake")
    assert_eq("default catalogs keys",
              sorted(state["catalogs"].keys()),
              ["actions", "gear", "resources", "skills"])


def case_default_state_returns_fresh_dict() -> None:
    a = empty_design_state()
    b = empty_design_state()
    a["phase"] = "ready"
    a["brief"]["assumptions"].append("mutated")
    assert_eq("fresh phase unchanged", b["phase"], "intake")
    assert_eq("fresh assumptions unchanged", b["brief"]["assumptions"], [])


def case_default_brief_and_taxonomy_keys() -> None:
    state = empty_design_state()
    assert_eq(
        "default brief keys",
        sorted(state["brief"].keys()),
        ["assumptions", "complexity", "concept", "genre", "tone"],
    )
    assert_eq(
        "default taxonomy keys",
        sorted(state["taxonomy"].keys()),
        ["complexity", "era", "genre", "setting_type", "tone"],
    )


def case_default_compile_block_idle() -> None:
    state = empty_design_state()
    cmp_block = state["compile"]
    assert_eq("default compile status", cmp_block["status"], "idle")
    assert_eq("default compile error empty", cmp_block["error"], "")
    assert_eq(
        "default compile parsed_v6_ref empty",
        cmp_block["parsed_v6_ref"], "",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    case_default_state_has_required_sections()
    case_default_state_returns_fresh_dict()
    case_default_brief_and_taxonomy_keys()
    case_default_compile_block_idle()
    print("\nAll design_state default-shape tests passed.")


if __name__ == "__main__":
    main()
