"""Unit tests for backend.agents.rule_editor.patch_ops.apply_ops.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_editor_patch_ops.py

Covers each op type, all-or-nothing rejection, and the recompile flag
propagation.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.patch_ops import (  # noqa: E402
    PatchError, apply_ops, parse_ops,
)
from agents.rule_editor.template import empty_v6  # noqa: E402


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}\n  expected: {expected!r}\n  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def case_set_meta() -> None:
    v6 = empty_v6()
    ops = parse_ops([
        {"op": "set_meta", "field": "book_title", "value": "Call of Cthulhu"},
        {"op": "set_meta", "field": "world_mode", "value": "horror"},
    ])
    res = apply_ops(v6, ops)
    assert_eq("set_meta book_title", res.parsed_v6["book_title"], "Call of Cthulhu")
    assert_eq("set_meta world_mode", res.parsed_v6["world_mode"], "horror")
    assert_eq("set_meta diff length", len(res.diff), 2)
    assert_eq("set_meta source untouched", v6["book_title"], "")
    assert_true(
        "set_meta does not flag dice/char_ui",
        not res.needs_dice_compile and not res.needs_character_ui_compile,
    )


def case_set_core_rules_and_patch() -> None:
    v6 = empty_v6()
    res = apply_ops(v6, parse_ops([
        {"op": "set_core_rules", "content": "# Core\n\nRoll 3d6 to start."},
    ]))
    assert_true(
        "set_core_rules wrote content",
        "Roll 3d6" in res.parsed_v6["core_rules"],
    )
    res2 = apply_ops(res.parsed_v6, parse_ops([
        {"op": "patch_core_rules", "find": "3d6", "replace": "2d10"},
    ]))
    assert_true(
        "patch_core_rules replaced",
        "2d10" in res2.parsed_v6["core_rules"]
        and "3d6" not in res2.parsed_v6["core_rules"],
    )


def case_patch_core_rules_ambiguous() -> None:
    v6 = empty_v6()
    v6["core_rules"] = "roll roll roll"
    try:
        apply_ops(v6, parse_ops([
            {"op": "patch_core_rules", "find": "roll", "replace": "x"},
        ]))
    except PatchError as e:
        assert_eq("patch_core_rules ambiguous code", e.code, "find_ambiguous")
        return
    fail("patch_core_rules ambiguous", "expected PatchError but none raised")


def case_patch_core_rules_not_found() -> None:
    v6 = empty_v6()
    v6["core_rules"] = "hello"
    try:
        apply_ops(v6, parse_ops([
            {"op": "patch_core_rules", "find": "nope", "replace": "x"},
        ]))
    except PatchError as e:
        assert_eq("patch_core_rules not_found code", e.code, "find_not_found")
        return
    fail("patch_core_rules not_found", "expected PatchError but none raised")


def case_set_companion() -> None:
    v6 = empty_v6()
    res = apply_ops(v6, parse_ops([
        {"op": "set_companion", "filename": "style_guide.md", "content": "noir"},
    ]))
    assert_eq("companion filename", res.parsed_v6["companion"]["filename"], "style_guide.md")
    assert_eq("companion content", res.parsed_v6["companion"]["content"], "noir")


def case_upsert_remove_rule_package() -> None:
    v6 = empty_v6()
    ops = parse_ops([
        {"op": "upsert_rule_package", "id": "combat",
         "package": {"content": "# Combat\n\n..."}},
        {"op": "upsert_rule_package", "id": "stealth",
         "package": {"content": "# Stealth\n\n..."}},
    ])
    res = apply_ops(v6, ops)
    assert_eq("upsert added 2 packages", len(res.parsed_v6["rule_packages"]), 2)
    assert_eq(
        "upsert sets package_id from id arg",
        res.parsed_v6["rule_packages"][0]["package_id"], "combat",
    )
    assert_true(
        "upsert flags dice recompile",
        res.needs_dice_compile,
    )
    # Update existing
    res2 = apply_ops(res.parsed_v6, parse_ops([
        {"op": "upsert_rule_package", "id": "combat",
         "package": {"content": "# Combat v2"}},
    ]))
    assert_eq("upsert updates in place (count unchanged)",
              len(res2.parsed_v6["rule_packages"]), 2)
    combat = next(
        p for p in res2.parsed_v6["rule_packages"] if p["package_id"] == "combat"
    )
    assert_eq("upsert updated content", combat["content"], "# Combat v2")
    # Remove
    res3 = apply_ops(res2.parsed_v6, parse_ops([
        {"op": "remove_rule_package", "id": "combat"},
    ]))
    assert_eq("remove dropped one", len(res3.parsed_v6["rule_packages"]), 1)
    assert_eq("remove kept stealth",
              res3.parsed_v6["rule_packages"][0]["package_id"], "stealth")


def case_remove_unknown_id_rejects() -> None:
    v6 = empty_v6()
    try:
        apply_ops(v6, parse_ops([
            {"op": "remove_rule_package", "id": "ghost"},
        ]))
    except PatchError as e:
        assert_eq("remove unknown id code", e.code, "not_found")
        return
    fail("remove unknown id", "expected PatchError")


def case_all_or_nothing_rollback() -> None:
    """A bad op in the middle of a batch must not partially apply."""
    v6 = empty_v6()
    v6["book_title"] = "Original"
    try:
        apply_ops(v6, parse_ops([
            {"op": "set_meta", "field": "book_title", "value": "New"},
            {"op": "remove_rule_package", "id": "ghost"},   # invalid
            {"op": "set_meta", "field": "world_mode", "value": "horror"},
        ]))
    except PatchError as e:
        assert_eq("rollback offending op_index", e.op_index, 1)
        # Source artifact must be untouched.
        assert_eq("rollback source book_title", v6["book_title"], "Original")
        assert_eq("rollback source world_mode", v6["world_mode"], "")
        return
    fail("all-or-nothing", "expected PatchError")


def case_upsert_remove_parameter_family() -> None:
    v6 = empty_v6()
    res = apply_ops(v6, parse_ops([
        {"op": "upsert_parameter_family", "id": "skills",
         "family": {"content": "...", "json": {"entries": []}}},
    ]))
    assert_eq("family added", len(res.parsed_v6["parameter_families"]), 1)
    assert_eq("family_id set", res.parsed_v6["parameter_families"][0]["family_id"], "skills")


def case_set_character_sheet() -> None:
    v6 = empty_v6()
    res = apply_ops(v6, parse_ops([
        {"op": "set_character_sheet",
         "template_json": {"fields": [{"name": "STR"}]},
         "guide_content": "## Creation"},
    ]))
    sheet = res.parsed_v6["character_sheet"]
    assert_eq("character_sheet template_json", sheet["template_json"]["fields"][0]["name"], "STR")
    assert_eq("character_sheet guide_content", sheet["guide_content"], "## Creation")
    assert_true("set_character_sheet flags character_ui recompile",
                res.needs_character_ui_compile)


def case_patch_character_sheet_field() -> None:
    v6 = empty_v6()
    v6 = apply_ops(v6, parse_ops([
        {"op": "set_character_sheet",
         "template_json": {"fields": [{"name": "STR", "default": 50}]}},
    ])).parsed_v6
    res = apply_ops(v6, parse_ops([
        {"op": "patch_character_sheet_field",
         "path": ["template_json", "fields", 0, "default"], "value": 60},
    ]))
    assert_eq(
        "patch_character_sheet_field updated nested",
        res.parsed_v6["character_sheet"]["template_json"]["fields"][0]["default"], 60,
    )


def case_patch_character_sheet_field_without_sheet() -> None:
    v6 = empty_v6()
    try:
        apply_ops(v6, parse_ops([
            {"op": "patch_character_sheet_field",
             "path": ["template_json", "x"], "value": 1},
        ]))
    except PatchError as e:
        assert_eq("patch_character_sheet_field no sheet code", e.code, "no_character_sheet")
        return
    fail("patch_character_sheet_field no sheet", "expected PatchError")


def case_mark_recompile() -> None:
    v6 = empty_v6()
    res = apply_ops(v6, parse_ops([
        {"op": "mark_recompile", "dice": True, "character_ui": False},
    ]))
    assert_true("mark_recompile dice", res.needs_dice_compile)
    assert_true("mark_recompile not character_ui", not res.needs_character_ui_compile)
    assert_eq("mark_recompile no diff", len(res.diff), 0)


def case_unknown_op_rejects() -> None:
    try:
        parse_ops([{"op": "do_a_barrel_roll"}])
    except PatchError as e:
        assert_eq("unknown op code", e.code, "unknown_op")
        return
    fail("unknown op", "expected PatchError")


def case_bad_id_rejects() -> None:
    v6 = empty_v6()
    try:
        apply_ops(v6, parse_ops([
            {"op": "upsert_rule_package", "id": "../etc",
             "package": {"content": "x"}},
        ]))
    except PatchError as e:
        assert_eq("bad_id code", e.code, "bad_id")
        return
    fail("bad id", "expected PatchError")


def case_pure_function() -> None:
    """apply_ops must not mutate the input dict."""
    v6 = empty_v6()
    snapshot = copy.deepcopy(v6)
    apply_ops(v6, parse_ops([
        {"op": "set_meta", "field": "book_title", "value": "X"},
        {"op": "upsert_rule_package", "id": "p1",
         "package": {"content": "..."}},
    ]))
    assert_eq("input dict untouched (deep equality)", v6, snapshot)


def main() -> None:
    case_set_meta()
    case_set_core_rules_and_patch()
    case_patch_core_rules_ambiguous()
    case_patch_core_rules_not_found()
    case_set_companion()
    case_upsert_remove_rule_package()
    case_remove_unknown_id_rejects()
    case_all_or_nothing_rollback()
    case_upsert_remove_parameter_family()
    case_set_character_sheet()
    case_patch_character_sheet_field()
    case_patch_character_sheet_field_without_sheet()
    case_mark_recompile()
    case_unknown_op_rejects()
    case_bad_id_rejects()
    case_pure_function()
    print("\nAll patch_ops tests passed.")


if __name__ == "__main__":
    main()
