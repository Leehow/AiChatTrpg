"""Persisted debug observation for the background NPC planner."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_npc.background_planner_constants import (
    _MAX_RUN_HISTORY,
    _PLANNER_STATE_KEY,
)
from services.trpg_npc.background_planner_utils import _int, _list_strings
from services.trpg_npc.optimization.background_observation_sanitizer import (
    sanitize_background_observation,
)
from services.trpg_npc.utils import now_iso


def append_background_planner_observation(
    session: GameSession,
    summary: dict[str, Any],
    *,
    max_runs: int = _MAX_RUN_HISTORY,
) -> dict[str, Any]:
    """Persist a compact debug run record onto the session JSON snapshot."""

    run = sanitize_background_observation(compact_background_planner_summary(summary))
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    state = dict(mem.get(_PLANNER_STATE_KEY)) if isinstance(mem.get(_PLANNER_STATE_KEY), dict) else {}
    runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    runs = [item for item in runs if isinstance(item, dict)]
    runs.append(run)
    cap = max(1, int(max_runs or _MAX_RUN_HISTORY))
    mem[_PLANNER_STATE_KEY] = {
        "version": 1,
        "latest": run,
        "runs": runs[-cap:],
    }
    session.memory_state = mem
    try:
        flag_modified(session, "memory_state")
    except Exception:
        pass
    return run


def compact_background_planner_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe, secret-free planner summary for debug storage."""

    skipped = str(summary.get("skipped") or "")
    status = str(summary.get("status") or "")
    if not status:
        status = "skipped" if skipped else "planned"
    json_snapshot = summary.get("json_snapshot")
    return {
        "mode": str(summary.get("mode") or "llm_background_action_board"),
        "status": status,
        "skipped": skipped,
        "based_on_turn_id": _int(summary.get("based_on_turn_id")),
        "model": str(summary.get("model") or ""),
        "considered": _int(summary.get("considered")),
        "selected": _int(summary.get("selected")),
        "selected_npc_ids": _list_strings(summary.get("selected_npc_ids")),
        "planned": _int(summary.get("planned")),
        "planned_card_ids": _list_strings(summary.get("planned_card_ids")),
        "persisted_action_cards": _int(summary.get("persisted_action_cards")),
        "structured_trigger_count": _int(summary.get("structured_trigger_count")),
        "legacy_trigger_count": _int(summary.get("legacy_trigger_count")),
        "secret_guard_transformed": _int(summary.get("secret_guard_transformed")),
        "secret_guard_blocked": _int(summary.get("secret_guard_blocked")),
        "knowledge_leak_warning_count": _int(summary.get("knowledge_leak_warning_count")),
        "knowledge_leak_blocked": _int(summary.get("knowledge_leak_blocked")),
        "knowledge_profile": (
            dict(summary.get("knowledge_profile"))
            if isinstance(summary.get("knowledge_profile"), dict)
            else {}
        ),
        "invalid_planner_cards": _int(summary.get("invalid_planner_cards")),
        "planner_card_build": (
            dict(summary.get("planner_card_build"))
            if isinstance(summary.get("planner_card_build"), dict)
            else {}
        ),
        "json_snapshot": dict(json_snapshot) if isinstance(json_snapshot, dict) else {},
        "updated_at": now_iso(),
    }


def background_planner_snapshot(session: GameSession) -> dict[str, Any]:
    """Read the stored planner debug snapshot from a session."""

    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    state = mem.get(_PLANNER_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}
