"""Primitive coercion and row accessor utilities for NPC Runtime V2 persistence.

Shared by the row builders, hydration decoders, DB upsert helpers, and the
pre-turn/snapshot builders.  Keeping these helpers in one place avoids
duplication when the persistence module is split for the 600-line policy.
"""

from __future__ import annotations

from typing import Any

from orm.models import GameSession
from services.trpg_npc.action_board import ActionBoard


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _row_json(row: Any, key: str) -> dict[str, Any]:
    value = _row_value(row, key)
    return dict(value) if isinstance(value, dict) else {}


def _active_npcs_from_session_json(session: GameSession) -> list[dict[str, Any]]:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    return [npc for npc in npcs if isinstance(npc, dict)] if isinstance(npcs, list) else []


def _action_board_from_rows(rows: list[Any]) -> ActionBoard:
    scenes: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        scene_id = str(_row_value(row, "scene_id") or "")
        card_json = _row_json(row, "card_json")
        if scene_id and card_json:
            scenes.setdefault(scene_id, []).append(card_json)
    return ActionBoard.from_dict({"version": 1, "scenes": scenes})


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _float_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _float(item) for key, item in value.items()}


def _result_rowcount(result: Any, *, fallback: int) -> int:
    rowcount = getattr(result, "rowcount", None)
    if isinstance(rowcount, int) and rowcount >= 0:
        return rowcount
    return fallback


def _row_id(*parts: str) -> str:
    return ":".join(str(part).replace(":", "_") for part in parts)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
