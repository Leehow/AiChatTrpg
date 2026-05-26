"""Strict template-driven character filter tests.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_character_template_filter.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.character_template_filter import (  # noqa: E402
    filter_card_by_template,
    render_template_schema_hint,
)


def assert_eq(label: str, got, want):
    if got != want:
        print(f"FAIL: {label}\n  got:  {got!r}\n  want: {want!r}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_true(label: str, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"OK: {label}")


def test_top_level_keys_outside_template_are_dropped():
    template = {"identity": {}, "attributes": {}, "skills": []}
    card = {
        "identity": {"name": "Frank"},
        "attributes": {},
        "armor_class": 14,  # ← LLM hallucination, not in template
        "spells": [],  # ← also not declared
    }
    filtered, dropped = filter_card_by_template(card, template)
    assert_eq("dropped count", len(dropped), 2)
    assert_true(
        "armor_class dropped",
        any(d["path"] == "armor_class" for d in dropped),
    )
    assert_true(
        "spells dropped",
        any(d["path"] == "spells" for d in dropped),
    )
    assert_eq(
        "kept keys",
        sorted(filtered.keys()),
        ["attributes", "identity"],
    )


def test_nested_dict_keys_outside_template_are_dropped():
    template = {
        "attributes": {
            "STR": {"value": None},
            "CON": {"value": None},
        },
    }
    card = {
        "attributes": {
            "STR": {"value": 60, "half": 30, "fifth": 12},
            "CON": {"value": 75, "half": 37},
            "CHA": {"value": 50},  # ← not in CoC, hallucination
        },
    }
    filtered, dropped = filter_card_by_template(card, template)
    assert_eq("CHA dropped count", len(dropped), 1)
    assert_eq(
        "CHA dropped path",
        dropped[0]["path"],
        "attributes.CHA",
    )
    # Critically: STR's runtime fields (half, fifth) survive even
    # though template only declares `value`. Leaf-object guard.
    assert_eq(
        "STR sub-fields preserved",
        sorted(filtered["attributes"]["STR"].keys()),
        ["fifth", "half", "value"],
    )


def test_skills_array_filtered_by_name():
    template = {
        "skills": [
            {"name": "侦查", "base": 25},
            {"name": "聆听", "base": 20},
        ],
    }
    card = {
        "skills": [
            {"name": "侦查", "value": 65},
            {"name": "聆听", "value": 50},
            {"name": "电气维修", "value": 25},  # ← not in template
            {"name": "斗殴", "value": 50},  # ← not in template
        ],
    }
    filtered, dropped = filter_card_by_template(card, template)
    assert_eq("dropped 2 skills", len(dropped), 2)
    names = sorted(s["name"] for s in filtered["skills"])
    assert_eq("kept names", names, ["侦查", "聆听"])


def test_empty_template_is_passthrough():
    card = {"anything": "goes", "more": [1, 2, 3]}
    filtered, dropped = filter_card_by_template(card, None)
    assert_eq("no drops on null template", len(dropped), 0)
    assert_eq("card unchanged", filtered, card)


def test_lists_without_name_field_are_not_filtered():
    # equipment.weapons is contextual — template provides empty list,
    # we do NOT enforce "no weapons in card" because the rules layer
    # for equipment is occupation-driven, not template-listed.
    template = {"equipment": {"weapons": [], "items": []}}
    card = {
        "equipment": {
            "weapons": [{"name": ".38", "damage": "1d10"}],
            "items": [{"name": "flashlight"}],
        },
    }
    filtered, dropped = filter_card_by_template(card, template)
    assert_eq("no drops for unnamed-template lists", len(dropped), 0)
    assert_eq(
        "weapons preserved",
        len(filtered["equipment"]["weapons"]),
        1,
    )


def test_schema_hint_renders():
    template = {
        "identity": {"name": None},
        "attributes": {"STR": {"value": None}, "DEX": {"value": None}},
        "skills": [
            {"name": "Investigation", "base": 25},
            {"name": "Listen", "base": 20},
        ],
        "equipment": {"weapons": [], "items": []},
    }
    hint = render_template_schema_hint(template)
    assert_true("hint mentions identity", "`identity`" in hint)
    assert_true("hint lists attribute keys", "STR" in hint and "DEX" in hint)
    assert_true(
        "hint lists skill names",
        "Investigation" in hint and "Listen" in hint,
    )
    assert_true("hint flags critical", "CRITICAL" in hint)


def test_strict_filter_combo_with_seed_overlay():
    # Simulates the real flow: mechanical_seed adds half/fifth siblings
    # to attributes.STR (already had `value` from LLM). Filter must
    # NOT drop those runtime sibling fields.
    template = {
        "attributes": {
            "STR": {"value": None},
            "CON": {"value": None},
        },
    }
    card_after_seed = {
        "attributes": {
            "STR": {"value": 70, "half": 35, "fifth": 14},
            "CON": {"value": 55, "half": 27, "fifth": 11},
        },
    }
    filtered, dropped = filter_card_by_template(card_after_seed, template)
    assert_eq("no drops in clean overlay", len(dropped), 0)
    assert_eq(
        "STR.half preserved",
        filtered["attributes"]["STR"]["half"],
        35,
    )


def main():
    test_top_level_keys_outside_template_are_dropped()
    test_nested_dict_keys_outside_template_are_dropped()
    test_skills_array_filtered_by_name()
    test_empty_template_is_passthrough()
    test_lists_without_name_field_are_not_filtered()
    test_schema_hint_renders()
    test_strict_filter_combo_with_seed_overlay()
    print("\nAll character_template_filter tests passed.")


if __name__ == "__main__":
    main()
