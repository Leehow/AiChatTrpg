"""Apply Runtime V2 table rows back onto the legacy session JSON snapshot.

Kept separate from `runtime_persistence` so the public facade stays under
the 600-line policy.  The function is re-exported from `runtime_persistence`
for the existing public import surface.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_npc.optimization.memory_compaction import compact_npc_memories
from services.trpg_npc.optimization.writeback_guard import (
    RuntimeWritebackPolicy,
    apply_runtime_snapshot_guarded,
)
from services.trpg_npc.runtime_adapter import (
    _current_scene_key,
    _session_turn_hint,
)
from services.trpg_npc.runtime_persistence_helpers import _row_json, _row_value


def apply_npc_runtime_v2_table_snapshot_to_session(
    session: GameSession,
    *,
    states: list[Any],
    relationships: list[Any],
    memories: list[Any],
    action_cards: list[Any],
    memory_cap: int = 20,
    current_turn: int | None = None,
    current_scene_id: str | None = None,
) -> dict[str, Any]:
    """Apply table row objects/dicts onto `session.memory_state`.

    This is pure relative to the database; tests and backfill diagnostics can
    use it without an AsyncSession.
    """

    summary: dict[str, Any] = {
        "states": 0,
        "relationships": 0,
        "memories": 0,
        "action_cards": 0,
        "missing_npcs": 0,
    }
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        summary["skipped_reason"] = "no_npcs"
        return summary

    by_id: dict[str, dict[str, Any]] = {}
    for npc in npcs:
        if isinstance(npc, dict):
            key = str(npc.get("key") or npc.get("name") or "").strip()
            if key:
                by_id[key] = npc

    guarded = apply_runtime_snapshot_guarded(
        session,
        states=states,
        relationships=relationships,
        memories=memories,
        action_cards=action_cards,
        current_turn=int(current_turn or _session_turn_hint(session) or 1),
        current_scene_id=current_scene_id or _current_scene_key(session) or None,
        policy=RuntimeWritebackPolicy(
            create_missing_npcs=False,
            # Table rows are already protected by conditional upserts.  Hydration
            # should still reject future/expired cards, but it should not treat
            # historical persisted rows as unsafe purely because their origin turn
            # is older than the foreground turn.
            max_background_lag_turns=1_000_000,
        ),
    )
    for key in ("states", "relationships", "memories", "action_cards"):
        summary[key] = int(guarded.applied.get(key, 0))
    summary["missing_npcs"] = sum(
        1 for item in guarded.rejected if item.reason == "missing_npc"
    )
    if guarded.rejected:
        summary["rejected_writebacks"] = len(guarded.rejected)
    if guarded.warnings:
        summary["writeback_warnings"] = len(guarded.warnings)

    cap = max(1, int(memory_cap or 20))
    touched_memory_npc_ids = {
        str(_row_value(row, "npc_id") or _row_json(row, "memory_json").get("npc_id") or "")
        for row in memories
    }
    for npc_id in touched_memory_npc_ids:
        if not npc_id:
            continue
        npc = by_id.get(npc_id)
        if not npc:
            continue
        items = npc.get("memories_v2") if isinstance(npc.get("memories_v2"), list) else []
        recent_cap = min(8, cap)
        important_cap = max(0, cap - recent_cap)
        compacted = compact_npc_memories(
            items,
            max_recent=recent_cap,
            max_important=important_cap,
            existing_archived_summary=(
                str(npc.get("memory_archive_summary_v2"))
                if npc.get("memory_archive_summary_v2")
                else None
            ),
        )
        npc["memories_v2"] = compacted.kept
        if compacted.archived_summary:
            npc["memory_archive_summary_v2"] = compacted.archived_summary
        if compacted.dropped_count:
            summary["archived_memories"] = summary.get("archived_memories", 0) + compacted.dropped_count

    changed = any(summary.get(key, 0) for key in ("states", "relationships", "memories", "action_cards"))
    if changed:
        mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else mem
        mem["npcs"] = npcs
        mem["_npc_runtime_tables_hydrated"] = {
            "summary": {k: v for k, v in summary.items() if isinstance(v, int)},
        }
        session.memory_state = mem
        try:
            flag_modified(session, "memory_state")
        except Exception:
            pass
    elif not any(summary.values()):
        summary["skipped_reason"] = "empty_tables"
    return summary
