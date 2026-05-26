"""Smoke tests for deterministic character-generation mechanics.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_character_generation_adapter.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.character_generation_adapter import (  # noqa: E402
    apply_character_mechanical_seed,
    build_character_mechanical_seed,
)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def _deep_ruleset() -> SimpleNamespace:
    return SimpleNamespace(
        id="rs-deep",
        parsed_v6={
            "core_rules": "HP = floor((CON + SIZ) / 10). FATE is rolled.",
            "character_sheet": {
                "guide_content": "生成 STR、CON、SIZ、DEX、PRE、INT、POW、EDU 和 FATE。",
                "template_json": {
                    "fields": {
                        "attributes": {
                            "STR": 50,
                            "CON": 50,
                            "SIZ": 50,
                            "DEX": 50,
                            "PRE": 50,
                            "INT": 50,
                            "POW": 50,
                            "EDU": 50,
                        },
                        "derived": {
                            "HP": 0,
                            "max_HP": 0,
                            "FOC": 0,
                            "max_FOC": 0,
                            "STA": 0,
                            "max_STA": 0,
                            "FATE": 0,
                            "MOV": 0,
                            "DB": "",
                        },
                    }
                },
            },
        },
    )


def _coc_ruleset() -> SimpleNamespace:
    attrs = {
        key.lower(): {"value": None, "half": None, "fifth": None}
        for key in ("STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK")
    }
    return SimpleNamespace(
        id="rs-coc",
        parsed_v6={
            "character_sheet": {
                "guide_content": (
                    "STR: 3D6 × 5; CON: 3D6 × 5; "
                    "SIZ: (2D6 + 6) × 5; Luck: 3D6 × 5."
                ),
                "template_json": {
                    "attributes": attrs,
                    "derived_values": {
                        "sanity": {"current": None, "starting": None, "maximum": None},
                        "magic_points": {"current": None, "maximum": None},
                        "hit_points": {"current": None, "maximum": None, "half_maximum": None},
                        "move_rate": {"value": None, "base_before_age": None},
                        "damage_bonus": None,
                        "build": None,
                        "dodge_base_from_dex_half": None,
                    },
                    "skills": [{"name": "Dodge", "base": None, "value": None, "half": None, "fifth": None}],
                },
            },
        },
    )


def case_deep_seed_is_deterministic_and_applies() -> None:
    first = build_character_mechanical_seed(
        _deep_ruleset(),
        session_id="sess-1",
        user_seed="journalist",
        mode="auto",
        transcript="I am a police archivist.",
    )
    second = build_character_mechanical_seed(
        _deep_ruleset(),
        session_id="sess-1",
        user_seed="journalist",
        mode="auto",
        transcript="I am a police archivist.",
    )
    assert_true("deep seed supported", first.supported, repr(first.to_metadata()))
    assert_eq("deep deterministic attrs", first.attributes, second.attributes)
    assert_true("deep rolls fate", "FATE" in first.attributes, repr(first.attributes))
    assert_eq("deep trace uses runtime dice", first.roll_trace[0]["roll_expression"], "3d6")

    card = {
        "fields": {
            "attributes": {key: 1 for key in ("STR", "CON", "SIZ", "DEX", "PRE", "INT", "POW", "EDU")},
            "derived": {"HP": 1, "max_HP": 1, "FOC": 1, "STA": 1, "FATE": 1},
        }
    }
    patched = apply_character_mechanical_seed(card, first)
    fields = patched["fields"]
    assert_eq("deep str applied", fields["attributes"]["STR"], first.attributes["STR"])
    assert_eq("deep hp applied", fields["derived"]["HP"], first.derived["HP"])
    assert_eq("deep audit attached", patched["_generation_audit"]["mechanical_seed"]["seed"], first.seed)


def case_coc_nested_card_gets_thresholds_and_derived() -> None:
    seed = build_character_mechanical_seed(
        _coc_ruleset(),
        session_id="sess-2",
        user_seed="",
        mode="from_chat",
        transcript="",
    )
    assert_true("coc seed supported", seed.supported, repr(seed.to_metadata()))
    card = _coc_ruleset().parsed_v6["character_sheet"]["template_json"]
    patched = apply_character_mechanical_seed(card, seed)
    str_box = patched["attributes"]["str"]
    dex = seed.attributes["DEX"]
    assert_eq("coc str value", str_box["value"], seed.attributes["STR"])
    assert_eq("coc str half", str_box["half"], seed.attributes["STR"] // 2)
    assert_eq("coc sanity starts pow", patched["derived_values"]["sanity"]["starting"], seed.attributes["POW"])
    assert_eq("coc hp maximum", patched["derived_values"]["hit_points"]["maximum"], seed.derived["HP"])
    assert_eq("coc siz trace rolls 2d6", seed.roll_trace[2]["roll_expression"], "2d6")
    assert_eq("coc dodge base", patched["skills"][0]["base"], dex // 2)


def main() -> None:
    case_deep_seed_is_deterministic_and_applies()
    case_coc_nested_card_gets_thresholds_and_derived()
    print("All character generation adapter cases passed.")


if __name__ == "__main__":
    main()
