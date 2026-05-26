"""Draft manifest builder tests.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_draft_manifest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.draft_manifest import (  # noqa: E402
    build_draft_manifest,
    render_manifest_for_prompt,
)


def assert_eq(label, got, want):
    if got != want:
        print(f"FAIL: {label}\n  got:  {got!r}\n  want: {want!r}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_true(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"OK: {label}")


def test_empty_draft():
    m = build_draft_manifest({})
    assert_eq("empty meta", m["meta"]["book_title"], "")
    assert_eq("empty core designed", m["core_rules"]["designed"], False)
    assert_eq("empty companion designed", m["companion"]["designed"], False)
    assert_eq("empty scenarios", m["scenarios"], [])
    assert_eq("empty families", m["parameter_families"], [])
    assert_eq("empty sheet designed", m["character_sheet"]["designed"], False)
    assert_eq("empty sheet scale", m["character_sheet"]["attribute_scale_hint"], "empty")
    assert_eq("empty dice", m["dice_ir"]["compiled"], False)


def test_attribute_scale_percentile():
    """CoC 7e style — defaults around 50."""
    parsed = {
        "character_sheet": {
            "template_json": {
                "attributes": {
                    "STR": {"value": 50}, "CON": {"value": 50}, "POW": {"value": 50},
                },
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("percentile detected", m["character_sheet"]["attribute_scale_hint"], "percentile")


def test_attribute_scale_low_integer():
    """CP2020 / WoD style — small ints."""
    parsed = {
        "character_sheet": {
            "template_json": {
                "attributes": {
                    "Body": {"value": 4}, "Reflex": {"value": 5}, "Tech": {"value": 3},
                },
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("low_integer detected", m["character_sheet"]["attribute_scale_hint"], "low_integer")


def test_attribute_scale_modifier():
    """D&D style modifier scale."""
    parsed = {
        "character_sheet": {
            "template_json": {
                "attributes": {
                    "STR": {"value": -1}, "DEX": {"value": 3}, "CON": {"value": 2},
                },
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("modifier detected", m["character_sheet"]["attribute_scale_hint"], "modifier")


def test_attribute_scale_unspecified():
    """Templates with null placeholders."""
    parsed = {
        "character_sheet": {
            "template_json": {
                "attributes": {"STR": {"value": None}, "CON": {"value": None}},
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("unspecified detected", m["character_sheet"]["attribute_scale_hint"], "unspecified")


def test_attribute_scale_supports_default_key():
    """Older templates use {default: 50}."""
    parsed = {
        "character_sheet": {
            "template_json": {
                "attributes": {"STR": {"default": 50}, "CON": {"default": 50}},
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("default-key handled", m["character_sheet"]["attribute_scale_hint"], "percentile")


def test_scenarios_index_keeps_first_line():
    parsed = {
        "rule_packages": [
            {"package_id": "creation", "title": "Creation", "content": "# Creation\n\nFirst line of body. More text."},
            {"package_id": "combat", "content": "# Combat\nQuick simple combat with d100."},
        ],
    }
    m = build_draft_manifest(parsed)
    assert_eq("scenario count", len(m["scenarios"]), 2)
    assert_eq("creation summary", m["scenarios"][0]["summary"], "Creation")
    assert_eq("creation chars", m["scenarios"][0]["chars"], len(parsed["rule_packages"][0]["content"]))


def test_families_index_extracts_shape_and_roster():
    parsed = {
        "parameter_families": [
            {
                "family_id": "occupation",
                "title": "Occupation",
                "json": {
                    "entries": [
                        {"name": "黑客", "summary": "网络入侵专家", "skill_points": 200, "credit_rating": 50},
                        {"name": "私家侦探", "summary": "调查专家", "skill_points": 200, "credit_rating": 30},
                    ],
                },
            },
        ],
    }
    m = build_draft_manifest(parsed)
    fam = m["parameter_families"][0]
    assert_eq("family entry count", fam["entry_count"], 2)
    assert_true(
        "shape includes name + summary",
        "name" in fam["entry_shape"] and "summary" in fam["entry_shape"],
    )
    assert_eq(
        "roster names",
        sorted(e["name"] for e in fam["entries_index"]),
        ["私家侦探", "黑客"],
    )


def test_dice_specs_carry_engine_hint():
    parsed = {
        "dice_ir": {
            "package": {
                "compiled": {
                    "default_procedure_id": "skill_check",
                    "check_specs": [
                        {
                            "procedure_id": "skill_check",
                            "name": "技能检定",
                            "check_spec": {"engine": "coc_7e_d100"},
                            "validation": {"ok": True},
                        },
                        {
                            "procedure_id": "save",
                            "name": "Save",
                            "check_spec": {"engine": "d20_vs_dc"},
                            "validation": {"ok": True},
                        },
                    ],
                },
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("dice spec count", len(m["dice_ir"]["specs"]), 2)
    assert_eq("d100 engine hint", m["dice_ir"]["specs"][0]["expects_skill_range"], "0-99 (percentile / d100)")
    assert_eq("d20 engine hint", m["dice_ir"]["specs"][1]["expects_skill_range"], "small modifier (e.g. -2..+10)")
    assert_eq("default pid", m["dice_ir"]["default_procedure_id"], "skill_check")


def test_render_block_format():
    m = build_draft_manifest({"book_title": "Test"})
    block = render_manifest_for_prompt(m)
    assert_true("contains heading", "Draft Manifest (auto-loaded)" in block)
    assert_true("contains code fence", "```json" in block and "```" in block)
    assert_true("contains book_title", "Test" in block)


def test_full_realistic_draft_smoke():
    """End-to-end shape check on a realistic mid-design draft."""
    parsed = {
        "book_title": "霓虹断层",
        "world_mode": "近未来赛博朋克",
        "output_language": "zh",
        "core_rules": "# 霓虹断层\n\n核心规则正文..." * 100,
        "companion": {"filename": "world_guide.md", "content": "霓虹之下..."},
        "rule_packages": [
            {"package_id": "creation", "content": "# 角色创建"},
            {"package_id": "hacking", "content": "# 黑客"},
        ],
        "parameter_families": [
            {
                "family_id": "occupation",
                "json": {
                    "entries": [
                        {"name": "黑客", "summary": "..."},
                    ],
                },
            },
        ],
        "character_sheet": {
            "template_json": {
                "identity": {},
                "attributes": {"Body": {"value": 4}, "Tech": {"value": 5}},
                "skills": [{"name": "侦查"}, {"name": "黑客"}],
            },
            "guide_content": "建卡指南..." * 30,
        },
        "dice_ir": {
            "package": {
                "compiled": {
                    "default_procedure_id": "skill_check",
                    "check_specs": [
                        {"procedure_id": "skill_check", "check_spec": {"engine": "coc_7e_d100"}, "validation": {"ok": True}},
                    ],
                },
            },
        },
    }
    m = build_draft_manifest(parsed)
    assert_eq("title", m["meta"]["book_title"], "霓虹断层")
    assert_eq("core_rules.designed", m["core_rules"]["designed"], True)
    assert_eq("companion.designed", m["companion"]["designed"], True)
    assert_eq("scenario count", len(m["scenarios"]), 2)
    assert_eq("family count", len(m["parameter_families"]), 1)
    assert_eq("sheet.designed", m["character_sheet"]["designed"], True)
    assert_eq("attr scale", m["character_sheet"]["attribute_scale_hint"], "low_integer")
    assert_eq("attr keys", m["character_sheet"]["attribute_keys"], ["Body", "Tech"])
    assert_eq("skills count", m["character_sheet"]["skills_count"], 2)
    assert_eq("dice compiled", m["dice_ir"]["compiled"], True)
    # The mismatch check the dice agent will see: low_integer attrs +
    # 0-99 d100 procedure → flag this combo to the agent.
    assert_eq(
        "scale mismatch surface visible",
        m["dice_ir"]["specs"][0]["expects_skill_range"],
        "0-99 (percentile / d100)",
    )


def main():
    test_empty_draft()
    test_attribute_scale_percentile()
    test_attribute_scale_low_integer()
    test_attribute_scale_modifier()
    test_attribute_scale_unspecified()
    test_attribute_scale_supports_default_key()
    test_scenarios_index_keeps_first_line()
    test_families_index_extracts_shape_and_roster()
    test_dice_specs_carry_engine_hint()
    test_render_block_format()
    test_full_realistic_draft_smoke()
    print("\nAll draft manifest tests passed.")


if __name__ == "__main__":
    main()
