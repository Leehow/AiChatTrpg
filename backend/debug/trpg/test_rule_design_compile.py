"""Pure-compiler tests for backend.agents.rule_editor.compile_design.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_compile.py

Covers a happy path (full compile emits every requested section + sets
stale flags) and a blocked path (validator blocks compile and the
caller observes CompileBlocked with a structured report). Service /
API smokes live next to the rest of the route smokes in
test_ruleset_drafts_routes.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.compile_design import (  # noqa: E402
    CompileBlocked,
    compile_design_state,
)
from agents.rule_editor.design_state import (  # noqa: E402
    apply_design_ops,
    empty_design_state,
    parse_design_ops,
)
from agents.rule_editor.template import empty_v6  # noqa: E402


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
# Fixtures
# ---------------------------------------------------------------------------


def _full_design_state() -> dict:
    """A design state that satisfies every blocking validator check."""
    state = empty_design_state()
    ops = parse_design_ops([
        {
            "op": "set_blueprint",
            "blueprint_id": "d20_heroic_adventure",
            "slots_required": [],
        },
        {
            "op": "set_brief_field", "field": "concept",
            "value": "Heroes raid the Crown Vault.\nDeep dungeon caper.",
        },
        {"op": "set_brief_field", "field": "tone", "value": "heroic"},
        {"op": "add_assumption", "assumption": "Magic is rare but real."},
        {"op": "set_taxonomy_field", "field": "genre", "value": "fantasy"},
        {
            "op": "set_taxonomy_field", "field": "setting_type",
            "value": "adventure",
        },
        {
            "op": "set_core_loop",
            "summary": "GM frames challenges; players act; checks resolve.",
            "phases": ["explore", "interaction", "combat"],
            "pacing": "scene-paced",
        },
        {
            "op": "set_resolution_model",
            "mechanic": "d20 vs DC",
            "dice": "1d20+mod",
            "success_thresholds": [
                {"name": "success", "rule": "total >= DC"},
                {"name": "critical", "rule": "natural 20"},
            ],
            "notes": "Higher is better.",
        },
        {
            "op": "set_character_model",
            "archetypes": ["fighter", "rogue"],
            "attributes": [
                {"id": "str", "name": "Strength"},
                {"id": "dex", "name": "Dexterity"},
            ],
            "derived_stats": [{"id": "hp", "name": "Hit Points"}],
            "progression_model": "level-based",
        },
        {
            "op": "upsert_procedure", "id": "combat",
            "procedure": {
                "name": "Combat",
                "summary": "Initiative -> turns -> resolve.",
                "steps": ["roll initiative", "act in order"],
            },
        },
        {
            "op": "upsert_catalog_entry", "catalog": "skills", "id": "athletics",
            "entry": {"id": "athletics", "name": "Athletics"},
        },
        {
            "op": "upsert_catalog_entry", "catalog": "skills", "id": "stealth",
            "entry": {"id": "stealth", "name": "Stealth"},
        },
        {
            "op": "upsert_catalog_entry", "catalog": "actions", "id": "attack",
            "entry": {"id": "attack", "name": "Attack"},
        },
    ])
    return apply_design_ops(state, ops).design_state


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def case_happy_path_emits_all_sections() -> None:
    state = _full_design_state()
    result = compile_design_state(state)

    parsed_v6 = result.parsed_v6
    assert_true(
        "happy: parsed_v6 has version 6", parsed_v6.get("version") == 6,
    )
    assert_eq(
        "happy: book_title inferred from concept",
        parsed_v6["book_title"], "Heroes raid the Crown Vault.",
    )
    assert_eq(
        "happy: world_mode from taxonomy.setting_type",
        parsed_v6["world_mode"], "adventure",
    )
    assert_eq(
        "happy: book_id empty when no base",
        parsed_v6["book_id"], "",
    )

    assert_true(
        "happy: core_rules contains Concept",
        "## Concept" in parsed_v6["core_rules"],
    )
    assert_true(
        "happy: core_rules contains Resolution",
        "Mechanic: d20 vs DC" in parsed_v6["core_rules"],
    )

    companion = parsed_v6["companion"]
    assert_eq(
        "happy: companion filename",
        companion["filename"], "world_guide.md",
    )
    assert_true(
        "happy: companion mentions blueprint",
        "d20_heroic_adventure" in companion["content"],
    )

    packages = parsed_v6["rule_packages"]
    assert_eq("happy: 1 rule_package emitted", len(packages), 1)
    assert_eq("happy: package_id", packages[0]["package_id"], "combat")
    assert_true(
        "happy: package content has steps",
        "## Steps" in packages[0]["content"],
    )

    families = parsed_v6["parameter_families"]
    family_ids = {f["family_id"] for f in families}
    assert_eq(
        "happy: families = skills + actions",
        family_ids, {"skills", "actions"},
    )
    skills_family = next(f for f in families if f["family_id"] == "skills")
    assert_eq(
        "happy: skills family has 2 entries",
        len(skills_family["json"]["entries"]), 2,
    )

    sheet = parsed_v6["character_sheet"]
    assert_true(
        "happy: character_sheet template_json",
        isinstance(sheet["template_json"], dict),
    )
    assert_eq(
        "happy: attributes keys",
        set(sheet["template_json"]["attributes"].keys()), {"str", "dex"},
    )
    assert_eq(
        "happy: skills mirrored into sheet",
        len(sheet["template_json"]["skills"]), 2,
    )
    assert_true(
        "happy: guide_content has heading",
        "# Character Guide" in sheet["guide_content"],
    )

    assert_true("happy: needs_dice_compile", result.needs_dice_compile)
    assert_true(
        "happy: needs_character_ui_compile",
        result.needs_character_ui_compile,
    )
    assert_eq(
        "happy: sections_emitted",
        sorted(result.sections_emitted),
        sorted([
            "meta", "core_rules", "companion",
            "rule_packages", "parameter_families", "character_sheet",
        ]),
    )


def case_meta_preserves_base_when_design_state_silent() -> None:
    state = _full_design_state()
    # Strip taxonomy.setting_type so world_mode falls back to base.
    state["taxonomy"]["setting_type"] = ""
    base = empty_v6()
    base["book_id"] = "rs_existing"
    base["world_mode"] = "horror"
    base["output_language"] = "en"

    result = compile_design_state(state, base_v6=base)
    assert_eq(
        "preserve: book_id from base", result.parsed_v6["book_id"], "rs_existing",
    )
    assert_eq(
        "preserve: world_mode falls back", result.parsed_v6["world_mode"], "horror",
    )
    assert_eq(
        "preserve: output_language from base",
        result.parsed_v6["output_language"], "en",
    )


# ---------------------------------------------------------------------------
# Blocked path
# ---------------------------------------------------------------------------


def case_blocked_when_validator_blocks() -> None:
    state = empty_design_state()
    try:
        compile_design_state(state)
    except CompileBlocked as exc:
        codes = sorted({iss.code for iss in exc.report.blocking})
        assert_true(
            "blocked: blueprint_required surfaces",
            "blueprint_required" in codes,
        )
        assert_true(
            "blocked: core_loop_summary_missing surfaces",
            "core_loop_summary_missing" in codes,
        )
        assert_eq(
            "blocked: can_compile false",
            exc.report.can_compile, False,
        )
        return
    fail("blocked", "expected CompileBlocked for empty design state")


def case_blocked_partial_state_keeps_parsed_v6_safe() -> None:
    """Confirm: with a partial state, the pure compiler does not even
    reach section emission."""
    state = empty_design_state()
    state["blueprint"]["id"] = "d20_heroic_adventure"
    # Missing core_loop, missing resolution_model -- still blocked.
    try:
        compile_design_state(state, base_v6=empty_v6())
    except CompileBlocked as exc:
        codes = sorted({iss.code for iss in exc.report.blocking})
        assert_true(
            "blocked-partial: still blocks on resolution",
            "resolution_mechanic_missing" in codes,
        )
        return
    fail("blocked-partial", "expected CompileBlocked for partial design state")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def case_deterministic_output() -> None:
    state = _full_design_state()
    a = compile_design_state(state).parsed_v6
    b = compile_design_state(state).parsed_v6
    assert_eq("deterministic: same parsed_v6", a, b)


# ---------------------------------------------------------------------------
# Boundary check
# ---------------------------------------------------------------------------


def case_engine_pure_no_app_imports() -> None:
    import agents.rule_editor.compile_design as mod
    src_files = [Path(mod.__file__).resolve()]
    src_files += [Path(__import__(name, fromlist=["x"]).__file__).resolve()
                  for name in (
                      "agents.rule_editor.compile_design_character",
                      "agents.rule_editor.compile_design_markdown",
                      "agents.rule_editor.compile_design_sections",
                  )]
    forbidden = ("fastapi", "sqlalchemy", "orm.", "services.")
    for path in src_files:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                fail(
                    "engine-pure",
                    f"{path.name} mentions `{needle}` (engine boundary leak)",
                )
    print("OK: engine-pure (compile_design + helpers have no app imports)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    case_happy_path_emits_all_sections()
    case_meta_preserves_base_when_design_state_silent()
    case_blocked_when_validator_blocks()
    case_blocked_partial_state_keeps_parsed_v6_safe()
    case_deterministic_output()
    case_engine_pure_no_app_imports()
    print("\nAll compile_design pure tests passed.")


if __name__ == "__main__":
    main()
