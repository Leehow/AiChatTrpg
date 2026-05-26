"""Projection from committed memories back to legacy memory_state.

``session.memory_state`` remains part of the current prompt/UI path. The commit
gate must be the authority, so legacy state is updated only from committed or
reinforced MemoryItem rows, never from raw AutoMemoryResult output.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_context.models import Visibility
from .memory_models import MemoryItem, MemoryKind

_MAX_RECENT_EVENTS = 60
_MAX_PLOT_THREADS = 40
_MAX_PLAYER_DISCOVERIES = 60


def project_committed_auto_memory_to_legacy_state(
    session: GameSession,
    items: Iterable[MemoryItem],
    *,
    turn_marker: str = "",
) -> dict[str, int]:
    """Update ``session.memory_state`` from committed MemoryItem objects."""

    committed = tuple(items)
    summary = {
        "events": 0,
        "plot_threads_upserted": 0,
        "plot_threads_added": 0,
        "discoveries": 0,
    }
    if not committed:
        return summary

    memory_state = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    changed = False

    recent = memory_state.get("recent_events")
    if not isinstance(recent, list):
        recent = []
    discoveries = memory_state.get("player_discoveries")
    if not isinstance(discoveries, list):
        discoveries = []
    threads = memory_state.get("plot_threads")
    if not isinstance(threads, list):
        threads = []

    idx_by_title: dict[str, int] = {}
    for i, thread in enumerate(threads):
        if isinstance(thread, dict):
            title_norm = _normalize_title(thread.get("title") or thread.get("key") or thread.get("name"))
            if title_norm:
                idx_by_title[title_norm] = i

    for item in committed:
        meta = dict(item.metadata or {})
        bucket = str(meta.get("legacy_bucket") or "")
        if bucket == "recent_events":
            entry = {
                "summary": item.text,
                "turn": turn_marker or item.created_at_turn or "",
                "memory_id": item.memory_id,
            }
            if _upsert_legacy_entry(recent, entry):
                summary["events"] += 1
                changed = True
            continue
        if bucket == "player_discoveries" or item.kind == MemoryKind.CLUE:
            if item.visibility not in {Visibility.PUBLIC, Visibility.PARTY_KNOWN}:
                continue
            entry = {
                "summary": item.text,
                "turn": turn_marker or item.created_at_turn or "",
                "memory_id": item.memory_id,
            }
            if _upsert_legacy_entry(discoveries, entry):
                summary["discoveries"] += 1
                changed = True
            continue
        if bucket == "plot_threads":
            title = str(meta.get("title") or "").strip()
            status = str(meta.get("status") or "active").strip() or "active"
            thread_summary = str(meta.get("summary") or item.text).strip()
            title_norm = _normalize_title(title)
            if title_norm and title_norm in idx_by_title:
                target = threads[idx_by_title[title_norm]]
                if isinstance(target, dict):
                    target["status"] = status
                    target["summary"] = thread_summary
                    target["last_turn"] = turn_marker or item.last_reinforced_turn or item.created_at_turn or ""
                    target["memory_id"] = item.memory_id
                    summary["plot_threads_upserted"] += 1
                    changed = True
                continue
            entry = {
                "title": title or item.text[:80],
                "status": status,
                "summary": thread_summary,
                "first_turn": turn_marker or item.created_at_turn or "",
                "last_turn": turn_marker or item.last_reinforced_turn or item.created_at_turn or "",
                "memory_id": item.memory_id,
            }
            threads.append(entry)
            if title_norm:
                idx_by_title[title_norm] = len(threads) - 1
            summary["plot_threads_added"] += 1
            changed = True

    if summary["events"]:
        memory_state["recent_events"] = recent[-_MAX_RECENT_EVENTS:]
    if summary["discoveries"]:
        memory_state["player_discoveries"] = discoveries[-_MAX_PLAYER_DISCOVERIES:]
    if summary["plot_threads_added"] or summary["plot_threads_upserted"]:
        memory_state["plot_threads"] = threads[-_MAX_PLOT_THREADS:]

    if changed:
        session.memory_state = memory_state
        flag_modified(session, "memory_state")
    return summary


def _upsert_legacy_entry(rows: list[Any], entry: dict[str, Any]) -> bool:
    memory_id = str(entry.get("memory_id") or "").strip()
    if not memory_id:
        rows.append(entry)
        return True
    changed = False
    duplicate_indexes: list[int] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("memory_id") != memory_id:
            continue
        if duplicate_indexes or any(
            isinstance(prev, dict) and prev.get("memory_id") == memory_id
            for prev in rows[:idx]
        ):
            duplicate_indexes.append(idx)
            continue
        for key, value in entry.items():
            if row.get(key) != value:
                row[key] = value
                changed = True
    for idx in reversed(duplicate_indexes):
        del rows[idx]
        changed = True
    if changed or duplicate_indexes:
        return changed
    if any(isinstance(row, dict) and row.get("memory_id") == memory_id for row in rows):
        return False
    rows.append(entry)
    return True


def _normalize_title(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())
