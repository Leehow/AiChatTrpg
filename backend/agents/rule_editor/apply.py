"""apply_ops — pure function that mutates a V6 artifact under patch ops.

Split out of patch_ops.py to keep file sizes in check. Op schemas and
parsing live in patch_ops; this module owns the imperative apply logic.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Union

from pydantic import BaseModel

from .patch_ops import (
    DiffEntry,
    MarkRecompile,
    PatchCharacterSheetField,
    PatchCoreRules,
    PatchError,
    PatchOp,
    RemoveParameterFamily,
    RemoveRulePackage,
    SetCharacterSheet,
    SetCompanion,
    SetCoreRules,
    SetMeta,
    UpsertParameterFamily,
    UpsertRulePackage,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]+$")


class ApplyResult(BaseModel):
    parsed_v6: dict[str, Any]
    diff: list[DiffEntry]
    needs_dice_compile: bool
    needs_character_ui_compile: bool


def apply_ops(
    parsed_v6: dict[str, Any],
    ops: list[PatchOp],
) -> ApplyResult:
    """Apply ops to a deep copy of `parsed_v6`. Pure — does not mutate input.

    Raises PatchError if any op is invalid against the current state.
    """
    new_v6 = copy.deepcopy(parsed_v6)
    diff: list[DiffEntry] = []
    needs_dice = False
    needs_char_ui = False

    for i, op in enumerate(ops):
        try:
            entries, dice_touched, char_ui_touched = _apply_one(new_v6, op)
        except PatchError as e:
            raise PatchError(i, e.code, e.message) from None
        diff.extend(entries)
        needs_dice = needs_dice or dice_touched
        needs_char_ui = needs_char_ui or char_ui_touched

    return ApplyResult(
        parsed_v6=new_v6,
        diff=diff,
        needs_dice_compile=needs_dice,
        needs_character_ui_compile=needs_char_ui,
    )


def _apply_one(
    v6: dict[str, Any], op: PatchOp,
) -> tuple[list[DiffEntry], bool, bool]:
    if isinstance(op, SetMeta):
        before = v6.get(op.field, "")
        v6[op.field] = op.value
        return [DiffEntry(path=[op.field], before=before, after=op.value)], False, False

    if isinstance(op, SetCoreRules):
        before = v6.get("core_rules", "")
        v6["core_rules"] = op.content
        return [DiffEntry(path=["core_rules"], before=before, after=op.content)], False, False

    if isinstance(op, PatchCoreRules):
        existing = v6.get("core_rules", "") or ""
        count = existing.count(op.find)
        if count == 0:
            raise PatchError(0, "find_not_found", "`find` text not found in core_rules")
        if count > 1:
            raise PatchError(
                0, "find_ambiguous",
                f"`find` text occurs {count} times; widen it to make it unique",
            )
        new_text = existing.replace(op.find, op.replace, 1)
        v6["core_rules"] = new_text
        return [DiffEntry(path=["core_rules"], before=existing, after=new_text)], False, False

    if isinstance(op, SetCompanion):
        before = v6.get("companion")
        new_companion = {"filename": op.filename, "content": op.content}
        v6["companion"] = new_companion
        return [DiffEntry(path=["companion"], before=before, after=new_companion)], False, False

    if isinstance(op, UpsertRulePackage):
        return _upsert_list_item(
            v6, "rule_packages", "package_id", op.id, op.package,
        ), True, False

    if isinstance(op, RemoveRulePackage):
        return _remove_list_item(
            v6, "rule_packages", "package_id", op.id,
        ), True, False

    if isinstance(op, UpsertParameterFamily):
        return _upsert_list_item(
            v6, "parameter_families", "family_id", op.id, op.family,
        ), True, False

    if isinstance(op, RemoveParameterFamily):
        return _remove_list_item(
            v6, "parameter_families", "family_id", op.id,
        ), True, False

    if isinstance(op, SetCharacterSheet):
        before = v6.get("character_sheet")
        new_sheet: dict[str, Any] = {}
        for k in (
            "template_json", "template_content", "template_filename",
            "guide_content", "guide_filename",
        ):
            v = getattr(op, k)
            if v is not None:
                new_sheet[k] = v
        v6["character_sheet"] = new_sheet
        return [DiffEntry(path=["character_sheet"], before=before, after=new_sheet)], False, True

    if isinstance(op, PatchCharacterSheetField):
        if not op.path:
            raise PatchError(0, "empty_path", "patch_character_sheet_field requires non-empty path")
        sheet = v6.get("character_sheet")
        if not isinstance(sheet, dict):
            raise PatchError(
                0, "no_character_sheet",
                "character_sheet does not exist; call set_character_sheet first",
            )
        before = _read_path(sheet, op.path)
        _write_path(sheet, op.path, op.value)
        return (
            [DiffEntry(path=["character_sheet", *op.path], before=before, after=op.value)],
            False, True,
        )

    if isinstance(op, MarkRecompile):
        return [], op.dice, op.character_ui

    raise PatchError(0, "unhandled_op", f"unhandled op type: {type(op).__name__}")


def _upsert_list_item(
    v6: dict[str, Any], list_key: str, id_field: str,
    item_id: str, payload: dict[str, Any],
) -> list[DiffEntry]:
    if not item_id or not _SAFE_ID.match(item_id):
        raise PatchError(0, "bad_id", f"id `{item_id}` is empty or contains unsafe characters")
    items = v6.setdefault(list_key, [])
    if not isinstance(items, list):
        raise PatchError(0, "bad_state", f"{list_key} is not a list")
    new_item = dict(payload)
    new_item[id_field] = item_id
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get(id_field) == item_id:
            before = copy.deepcopy(existing)
            items[idx] = new_item
            return [DiffEntry(path=[list_key, item_id], before=before, after=new_item)]
    items.append(new_item)
    return [DiffEntry(path=[list_key, item_id], before=None, after=new_item)]


def _remove_list_item(
    v6: dict[str, Any], list_key: str, id_field: str, item_id: str,
) -> list[DiffEntry]:
    items = v6.get(list_key)
    if not isinstance(items, list):
        raise PatchError(0, "not_found", f"{list_key} is empty or missing")
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get(id_field) == item_id:
            before = copy.deepcopy(existing)
            del items[idx]
            return [DiffEntry(path=[list_key, item_id], before=before, after=None)]
    raise PatchError(0, "not_found", f"{list_key}[{id_field}={item_id}] not found")


def _read_path(root: Any, path: list[Union[str, int]]) -> Any:
    cur = root
    for key in path:
        if isinstance(cur, dict) and isinstance(key, str):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            cur = cur[key] if 0 <= key < len(cur) else None
        else:
            return None
    return cur


def _write_path(root: Any, path: list[Union[str, int]], value: Any) -> None:
    if not path:
        raise PatchError(0, "empty_path", "cannot write at empty path")
    cur = root
    for key in path[:-1]:
        if isinstance(cur, dict) and isinstance(key, str):
            nxt = cur.get(key)
            if nxt is None:
                nxt = {}
                cur[key] = nxt
            cur = nxt
        elif isinstance(cur, list) and isinstance(key, int):
            if not (0 <= key < len(cur)):
                raise PatchError(0, "bad_path", f"index {key} out of range at {path}")
            cur = cur[key]
        else:
            raise PatchError(0, "bad_path", f"cannot traverse key {key!r} at {path}")
    last = path[-1]
    if isinstance(cur, dict) and isinstance(last, str):
        cur[last] = value
    elif isinstance(cur, list) and isinstance(last, int):
        if not (0 <= last < len(cur)):
            raise PatchError(0, "bad_path", f"final index {last} out of range")
        cur[last] = value
    else:
        raise PatchError(0, "bad_path", f"cannot write key {last!r} into {type(cur).__name__}")
