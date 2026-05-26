"""Undo logic for the rule editor draft.

Linear undo only: applies the inverse of a single edit's diff against the
*current* state, ignoring any later edits that touched the same fields.
The frontend warns the user about this trade-off.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import Ruleset, RulesetDraft, RulesetDraftEdit


_LIST_ID_KEYS = {
    "rule_packages": "package_id",
    "parameter_families": "family_id",
}


async def undo_edit(
    db: AsyncSession,
    *,
    draft: RulesetDraft,
    owner_id: str,
    edit_id: str,
    new_id_factory: Any,
) -> RulesetDraftEdit:
    """Reverse a single edit. Caller has already auth-checked the draft."""
    edit = await db.get(RulesetDraftEdit, edit_id)
    if edit is None or edit.draft_id != draft.id:
        raise HTTPException(404, "Edit not found")
    if edit.undone:
        raise HTTPException(400, "Edit already undone")

    new_v6 = copy.deepcopy(draft.parsed_v6 or {})
    inverse_diff: list[dict[str, Any]] = []
    for d in edit.diff:
        path = d.get("path") or []
        before = d.get("before")
        after_now = _read_path(new_v6, path)
        _undo_write(new_v6, path, before)
        inverse_diff.append({"path": path, "before": after_now, "after": before})

    draft.parsed_v6 = new_v6
    flag_modified(draft, "parsed_v6")
    edit.undone = True

    if draft.target_ruleset_id:
        target = await db.get(Ruleset, draft.target_ruleset_id)
        if target is not None and target.owner_id == owner_id:
            target.parsed_v6 = copy.deepcopy(new_v6)
            flag_modified(target, "parsed_v6")
            target.book_title = str(new_v6.get("book_title") or "")
            target.world_mode = str(new_v6.get("world_mode") or "")
            target.book_id = str(new_v6.get("book_id") or "")
            target.updated_at = datetime.now(timezone.utc)

    inverse_edit = RulesetDraftEdit(
        id=new_id_factory("edit"),
        draft_id=draft.id,
        message_id=None,
        ops=[{"op": "_undo_of", "edit_id": edit.id}],
        diff=inverse_diff,
        undone=False,
    )
    db.add(inverse_edit)
    await db.commit()
    await db.refresh(inverse_edit)
    await db.refresh(draft)
    return inverse_edit


def _read_path(root: Any, path: list[Any]) -> Any:
    cur = root
    for key in path:
        if isinstance(cur, dict) and isinstance(key, str):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            cur = cur[key] if 0 <= key < len(cur) else None
        else:
            return None
    return cur


def _undo_write(root: Any, path: list[Any], value: Any) -> None:
    """Write `value` back at `path`. Handles list-of-dicts by id key.

    The diff format produced by patch_ops uses logical ids
    (`["rule_packages", "<id>"]`) for stable refs across reorders, not
    array indices. We translate id → array index here.
    """
    if not path:
        return
    cur = root
    for key in path[:-1]:
        if isinstance(cur, dict) and isinstance(key, str):
            nxt = cur.get(key)
            if nxt is None:
                nxt = {}
                cur[key] = nxt
            cur = nxt
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return
    last = path[-1]
    parent_key = path[-2] if len(path) >= 2 else None
    if isinstance(cur, list) and isinstance(parent_key, str) and parent_key in _LIST_ID_KEYS:
        id_field = _LIST_ID_KEYS[parent_key]
        idx = next(
            (i for i, item in enumerate(cur)
             if isinstance(item, dict) and item.get(id_field) == last),
            None,
        )
        if value is None:
            if idx is not None:
                del cur[idx]
        else:
            if idx is None:
                cur.append(value)
            else:
                cur[idx] = value
        return
    if isinstance(cur, dict) and isinstance(last, str):
        if value is None:
            cur.pop(last, None)
        else:
            cur[last] = value
    elif isinstance(cur, list) and isinstance(last, int) and 0 <= last < len(cur):
        cur[last] = value
