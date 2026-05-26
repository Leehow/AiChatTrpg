"""Unit tests for backend.agents.rule_editor.blueprints.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_blueprints.py

Covers the read-only catalogue, deterministic recommend/apply, and the
non-overwriting merge contract.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.blueprints import (  # noqa: E402
    BlueprintNotFoundError,
    apply_blueprint,
    get_blueprint,
    list_blueprints,
    recommend_blueprints,
)
from agents.rule_editor.design_state import (  # noqa: E402
    apply_design_ops,
    empty_design_state,
    parse_design_ops,
    validate_design_state,
)


EXPECTED_IDS = {
    "d20_heroic_adventure",
    "d100_investigation_horror",
    "traditional_fantasy_adventure",
    "mission_anomaly_containment",
    "cyberpunk_job_based",
}


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
# Catalogue
# ---------------------------------------------------------------------------


def case_list_blueprints_returns_five() -> None:
    bps = list_blueprints()
    ids = {bp["id"] for bp in bps}
    assert_eq("blueprint count", len(bps), 5)
    assert_eq("blueprint ids match expected", ids, EXPECTED_IDS)


def case_each_blueprint_has_required_fields() -> None:
    required = (
        "id", "name", "summary", "taxonomy", "slots_required",
        "defaults", "keywords",
    )
    for bp in list_blueprints():
        for key in required:
            assert_true(
                f"blueprint {bp.get('id')} has {key}",
                key in bp,
            )
        assert_true(
            f"blueprint {bp['id']} slots_required non-empty",
            bool(bp["slots_required"]),
        )


def case_list_blueprints_returns_fresh_copies() -> None:
    a = list_blueprints()
    a[0]["taxonomy"]["genre"] = "MUTATED"
    b = list_blueprints()
    assert_true(
        "second list call is unaffected by mutation",
        b[0]["taxonomy"]["genre"] != "MUTATED",
    )


def case_get_blueprint_known_and_unknown() -> None:
    bp = get_blueprint("d100_investigation_horror")
    assert_true("known blueprint resolved", bp is not None)
    assert_eq("known blueprint id",
              bp["id"], "d100_investigation_horror")
    assert_eq("unknown blueprint returns None",
              get_blueprint("nope"), None)


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def case_recommend_by_keyword_horror() -> None:
    picks = recommend_blueprints(
        text="I want a Cthulhu-style modern investigation horror"
    )
    assert_true("recommend returns at least 1", len(picks) >= 1)
    assert_eq(
        "horror keywords pick d100_investigation_horror first",
        picks[0]["id"], "d100_investigation_horror",
    )


def case_recommend_by_keyword_cyberpunk() -> None:
    picks = recommend_blueprints(text="cyberpunk runner job")
    assert_eq(
        "cyberpunk picks cyberpunk_job_based first",
        picks[0]["id"], "cyberpunk_job_based",
    )


def case_recommend_by_taxonomy_match() -> None:
    picks = recommend_blueprints(
        text="",
        taxonomy={"genre": "fantasy", "tone": "heroic"},
    )
    assert_eq(
        "taxonomy match picks d20_heroic_adventure first",
        picks[0]["id"], "d20_heroic_adventure",
    )


def case_recommend_is_deterministic() -> None:
    a = recommend_blueprints(text="anomaly mission")
    b = recommend_blueprints(text="anomaly mission")
    assert_eq("two recommend calls equal", a, b)


def case_recommend_limit_zero_returns_empty() -> None:
    assert_eq(
        "limit 0 returns empty list",
        recommend_blueprints(text="anything", limit=0), [],
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def case_apply_blueprint_seeds_sections() -> None:
    state = empty_design_state()
    snapshot = copy.deepcopy(state)
    res = apply_blueprint(state, "d100_investigation_horror")
    assert_eq("input not mutated", state, snapshot)
    new = res.design_state
    assert_eq("blueprint id set",
              new["blueprint"]["id"], "d100_investigation_horror")
    assert_true(
        "core_loop summary seeded",
        bool(new["core_loop"]["summary"]),
    )
    assert_true(
        "resolution mechanic seeded",
        bool(new["resolution_model"]["mechanic"]),
    )
    assert_true(
        "character attributes seeded",
        len(new["character_model"]["attributes"]) > 0,
    )
    assert_eq(
        "taxonomy genre seeded",
        new["taxonomy"]["genre"], "horror",
    )
    expected_slots = {
        "core_loop", "resolution_model", "character_attributes",
        "sanity_track", "skills_catalog",
    }
    assert_eq(
        "slots seeded as missing",
        set(new["slots"].keys()), expected_slots,
    )


def case_apply_blueprint_does_not_overwrite_existing() -> None:
    state = empty_design_state()
    seeded = apply_design_ops(state, parse_design_ops([
        {"op": "set_core_loop", "summary": "user-authored loop"},
        {"op": "set_taxonomy_field", "field": "genre", "value": "weird"},
    ])).design_state
    res = apply_blueprint(seeded, "d20_heroic_adventure")
    new = res.design_state
    assert_eq(
        "user core_loop summary preserved",
        new["core_loop"]["summary"], "user-authored loop",
    )
    assert_eq(
        "user taxonomy genre preserved",
        new["taxonomy"]["genre"], "weird",
    )
    assert_true(
        "blueprint still recorded",
        new["blueprint"]["id"] == "d20_heroic_adventure",
    )


def case_apply_blueprint_unknown_raises() -> None:
    state = empty_design_state()
    try:
        apply_blueprint(state, "totally_made_up")
    except BlueprintNotFoundError:
        print("OK: unknown blueprint raises BlueprintNotFoundError")
        return
    fail("unknown blueprint apply", "expected BlueprintNotFoundError")


def case_apply_blueprint_then_validate_progress() -> None:
    state = empty_design_state()
    res = apply_blueprint(state, "d100_investigation_horror")
    new = apply_design_ops(res.design_state, parse_design_ops([
        {"op": "set_brief_field", "field": "concept",
         "value": "noir mystery"},
    ])).design_state
    report = validate_design_state(new)
    assert_true(
        "validator still blocks compile (slots not filled)",
        not report.can_compile,
    )
    blocking_codes = {iss.code for iss in report.blocking}
    assert_true(
        "blueprint_required not blocking after apply",
        "blueprint_required" not in blocking_codes,
    )
    assert_true(
        "core_loop_summary_missing not blocking after seed",
        "core_loop_summary_missing" not in blocking_codes,
    )
    assert_eq(
        "required slot count from blueprint",
        len(report.slots.required), 5,
    )


def case_apply_blueprint_is_deterministic() -> None:
    a = apply_blueprint(empty_design_state(), "cyberpunk_job_based")
    b = apply_blueprint(empty_design_state(), "cyberpunk_job_based")
    assert_eq("two apply calls equal design_state",
              a.design_state, b.design_state)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    case_list_blueprints_returns_five()
    case_each_blueprint_has_required_fields()
    case_list_blueprints_returns_fresh_copies()
    case_get_blueprint_known_and_unknown()
    case_recommend_by_keyword_horror()
    case_recommend_by_keyword_cyberpunk()
    case_recommend_by_taxonomy_match()
    case_recommend_is_deterministic()
    case_recommend_limit_zero_returns_empty()
    case_apply_blueprint_seeds_sections()
    case_apply_blueprint_does_not_overwrite_existing()
    case_apply_blueprint_unknown_raises()
    case_apply_blueprint_then_validate_progress()
    case_apply_blueprint_is_deterministic()
    print("\nAll blueprint tests passed.")


if __name__ == "__main__":
    main()
