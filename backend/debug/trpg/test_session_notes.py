"""Player-notes CRUD helpers used by ``backend/routes/session_notes.py``.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_session_notes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from routes.session_notes import (  # noqa: E402
    _normalize_note,
    _normalize_tags,
    add_note,
    delete_note,
    update_note,
)


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def assert_eq(name: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{name} failed: expected {expected!r}, got {actual!r}")
    print(f"OK: {name}")


def case_normalize_tags_trims_dedups_drops_blanks() -> None:
    tags = _normalize_tags(["  fire  ", "fire", "", None, "ice", "ICE"])
    assert_eq("tags trimmed and deduped", tags, ["fire", "ice", "ICE"])
    assert_eq("non-list returns empty", _normalize_tags(None), [])


def case_normalize_note_accepts_legacy_marker_shape() -> None:
    # Shape minted by services/trpg_ic_markers._extract_note — no `source`.
    legacy = {
        "id": "legacy-1",
        "content": "the door tag read 'R. Russell'",
        "tags": ["clue"],
        "created_at": "2026-05-18T00:00:00+00:00",
    }
    out = _normalize_note(legacy)
    assert_true("legacy note normalized", out is not None)
    assert_eq("legacy id preserved", out["id"], "legacy-1")
    assert_eq("legacy source defaulted to gm", out["source"], "gm")
    assert_eq("legacy tags preserved", out["tags"], ["clue"])


def case_normalize_note_mints_id_when_missing() -> None:
    out = _normalize_note({"content": "no id here", "tags": []})
    assert_true("id minted", isinstance(out["id"], str) and len(out["id"]) > 0)
    assert_eq("missing source defaults to gm", out["source"], "gm")


def case_normalize_note_drops_blank_content() -> None:
    assert_true("blank dropped", _normalize_note({"content": "   "}) is None)
    assert_true("non-dict dropped", _normalize_note("not a dict") is None)


def case_add_note_creates_player_note() -> None:
    memory_state: dict = {}
    note = add_note(memory_state, content="found a key", tags=["loot"])
    assert_eq("source is player", note["source"], "player")
    assert_eq("content trimmed", note["content"], "found a key")
    assert_eq("tags normalized", note["tags"], ["loot"])
    assert_true("created_at set", isinstance(note["created_at"], str) and note["created_at"])
    assert_true("updated_at null", note["updated_at"] is None)
    assert_eq("bucket has one note", len(memory_state["player_notes"]), 1)


def case_add_note_rejects_empty_content() -> None:
    try:
        add_note({}, content="   ", tags=[])
    except ValueError as exc:
        assert_true("empty rejected with ValueError", "empty" in str(exc))
        return
    raise AssertionError("add_note should reject blank content")


def case_add_note_preserves_existing_marker_notes() -> None:
    # Mimic a session whose memory_state already carries an [ADD_NOTE] row.
    memory_state = {
        "player_notes": [
            {
                "id": "gm-1",
                "content": "lab door is locked",
                "tags": [],
                "created_at": "2026-05-18T01:00:00+00:00",
            },
        ],
    }
    new = add_note(memory_state, content="check the desk drawer", tags=["todo"])
    bucket = memory_state["player_notes"]
    assert_eq("bucket grew to 2", len(bucket), 2)
    assert_eq("legacy id preserved", bucket[0]["id"], "gm-1")
    assert_eq("legacy normalized source", bucket[0]["source"], "gm")
    assert_eq("new note appended", bucket[1]["id"], new["id"])


def case_update_note_patches_content_and_tags() -> None:
    memory_state: dict = {}
    note = add_note(memory_state, content="initial", tags=["a"])
    patched = update_note(
        memory_state, note["id"], content="updated text", tags=["a", "b"],
    )
    assert_eq("content updated", patched["content"], "updated text")
    assert_eq("tags updated", patched["tags"], ["a", "b"])
    assert_true("updated_at set", isinstance(patched["updated_at"], str) and patched["updated_at"])


def case_update_note_partial_keeps_other_fields() -> None:
    memory_state: dict = {}
    note = add_note(memory_state, content="initial", tags=["a"])
    patched = update_note(memory_state, note["id"], content="just content")
    assert_eq("content changed", patched["content"], "just content")
    assert_eq("tags preserved when omitted", patched["tags"], ["a"])


def case_update_note_rejects_missing_id() -> None:
    try:
        update_note({"player_notes": []}, "nope", content="x")
    except KeyError:
        print("OK: update_note raises KeyError on missing id")
        return
    raise AssertionError("update_note should raise KeyError for missing id")


def case_update_note_rejects_blank_content() -> None:
    memory_state: dict = {}
    note = add_note(memory_state, content="initial", tags=[])
    try:
        update_note(memory_state, note["id"], content="   ")
    except ValueError:
        print("OK: update_note rejects blank content")
        return
    raise AssertionError("update_note should reject blank content")


def case_delete_note_removes_target() -> None:
    memory_state: dict = {}
    a = add_note(memory_state, content="a", tags=[])
    b = add_note(memory_state, content="b", tags=[])
    delete_note(memory_state, a["id"])
    ids = [n["id"] for n in memory_state["player_notes"]]
    assert_eq("only b remains", ids, [b["id"]])


def case_delete_note_missing_raises() -> None:
    try:
        delete_note({"player_notes": []}, "nope")
    except KeyError:
        print("OK: delete_note raises KeyError on missing id")
        return
    raise AssertionError("delete_note should raise KeyError for missing id")


def case_update_note_rejects_gm_source() -> None:
    # Normalized legacy [ADD_NOTE] row — source defaults to "gm" on first
    # read, and edits must bounce with PermissionError (route → 403).
    memory_state = {
        "player_notes": [
            {
                "id": "gm-1",
                "content": "lab door is locked",
                "tags": [],
                "created_at": "2026-05-18T01:00:00+00:00",
            },
        ],
    }
    try:
        update_note(memory_state, "gm-1", content="trying to edit")
    except PermissionError:
        # GM note must remain unchanged after the rejected attempt.
        assert_eq(
            "gm content preserved",
            memory_state["player_notes"][0]["content"],
            "lab door is locked",
        )
        print("OK: update_note raises PermissionError on gm source")
        return
    raise AssertionError("update_note should raise PermissionError for gm-sourced note")


def case_delete_note_rejects_gm_source() -> None:
    memory_state = {
        "player_notes": [
            {
                "id": "gm-1",
                "content": "the door tag read 'R. Russell'",
                "tags": ["clue"],
                "created_at": "2026-05-18T01:00:00+00:00",
            },
        ],
    }
    try:
        delete_note(memory_state, "gm-1")
    except PermissionError:
        assert_eq(
            "gm row preserved after rejected delete",
            len(memory_state["player_notes"]),
            1,
        )
        print("OK: delete_note raises PermissionError on gm source")
        return
    raise AssertionError("delete_note should raise PermissionError for gm-sourced note")


def case_update_delete_still_work_on_player_notes_after_gm_rejection() -> None:
    # Mixed bucket: a legacy GM row + a fresh player row. The GM row stays
    # read-only; the player row remains fully mutable.
    memory_state: dict = {
        "player_notes": [
            {
                "id": "gm-1",
                "content": "GM-recorded clue",
                "tags": [],
                "created_at": "2026-05-18T00:00:00+00:00",
            },
        ],
    }
    player_note = add_note(memory_state, content="my note", tags=["todo"])
    # Rejected GM mutation.
    try:
        update_note(memory_state, "gm-1", content="hacked")
    except PermissionError:
        pass
    # Player mutation still succeeds.
    patched = update_note(memory_state, player_note["id"], content="my updated note")
    assert_eq("player update applied", patched["content"], "my updated note")
    delete_note(memory_state, player_note["id"])
    ids_after = [n["id"] for n in memory_state["player_notes"]]
    assert_eq("only gm row remains", ids_after, ["gm-1"])


def main() -> None:
    case_normalize_tags_trims_dedups_drops_blanks()
    case_normalize_note_accepts_legacy_marker_shape()
    case_normalize_note_mints_id_when_missing()
    case_normalize_note_drops_blank_content()
    case_add_note_creates_player_note()
    case_add_note_rejects_empty_content()
    case_add_note_preserves_existing_marker_notes()
    case_update_note_patches_content_and_tags()
    case_update_note_partial_keeps_other_fields()
    case_update_note_rejects_missing_id()
    case_update_note_rejects_blank_content()
    case_delete_note_removes_target()
    case_delete_note_missing_raises()
    case_update_note_rejects_gm_source()
    case_delete_note_rejects_gm_source()
    case_update_delete_still_work_on_player_notes_after_gm_rejection()
    print("All session-notes cases passed.")


if __name__ == "__main__":
    main()
