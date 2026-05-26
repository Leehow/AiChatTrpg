"""Message-timeline and JSON helpers for IC turn runner.

Extracted from `services.trpg_ic_runner`. These helpers cover loading the
recent chat timeline, snapshotting the current scene/time tag for per-message
metadata, the JSON-coercion used by snapshot payloads, and persistence of new
IC messages. Behavior and signatures are unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, Message


_IC_PHASE = "ic"
_RECENT_HISTORY_LIMIT = 30


async def _load_recent_messages(
    db: AsyncSession, session_id: str, *, limit: int = _RECENT_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """Load the recent N messages (any phase) ordered oldest → newest, in the
    legacy dict shape `to_session_state` expects."""
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    out: list[dict[str, Any]] = []
    for m in rows:
        out.append({
            "role": "assistant" if m.role == "gm" else m.role,
            "content": m.content or "",
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "metadata": dict(m.metadata_json or {}),
        })
    return out


def _current_scene_tag(session: GameSession) -> dict[str, Any]:
    """Snapshot current scene/time for per-message timeline UI.

    Scene fields let the message list group rows without rescanning marker
    bodies. ``current_time`` lets the floating HUD follow the message currently
    being read instead of always showing the latest session state.
    """
    ms = session.module_state if isinstance(session.module_state, dict) else {}
    out: dict[str, Any] = {}
    key = ms.get("scene")
    if isinstance(key, str) and key.strip() and key.strip() != "—":
        out["scene_key"] = key.strip()
    name = ms.get("scene_name")
    if isinstance(name, str) and name.strip() and name.strip() != "—":
        out["scene_name"] = name.strip()
    current_time: dict[str, Any] = {}
    day = ms.get("day_count")
    if isinstance(day, int) and not isinstance(day, bool):
        current_time["day"] = day
    elif isinstance(day, str) and day.strip():
        current_time["day"] = day.strip()
    clock = ms.get("in_game_time")
    clock_text = clock.strip() if isinstance(clock, str) else ""
    if clock_text and clock_text != "—":
        current_time["clock"] = clock_text
    date = ms.get("in_game_date")
    if isinstance(date, str) and date.strip():
        current_time["date"] = date.strip()
    period = ms.get("in_game_period")
    period_text = (
        _period_key_from_clock(clock_text)
        if clock_text else (period.strip() if isinstance(period, str) else "")
    )
    if period_text:
        current_time["period"] = period_text
    if current_time:
        out["current_time"] = current_time
    return out


def _period_key_from_clock(clock: str) -> str:
    try:
        hour = int(str(clock).split(":", 1)[0])
    except (TypeError, ValueError):
        return ""
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(v) for v in value]
    return str(value)


async def _save_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    session: GameSession | None = None,
) -> Message | None:
    if not content:
        return None
    db_role = "gm" if role == "assistant" else role
    if db_role not in ("user", "gm", "system", "dice"):
        return None
    meta: dict[str, Any] = dict(metadata or {})
    meta.setdefault("phase", _IC_PHASE)
    if session is not None:
        for k, v in _current_scene_tag(session).items():
            meta.setdefault(k, v)
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=db_role,
        content=content,
        metadata_json=meta,
    )
    db.add(msg)
    return msg


__all__ = [
    "_IC_PHASE",
    "_RECENT_HISTORY_LIMIT",
    "_load_recent_messages",
    "_current_scene_tag",
    "_period_key_from_clock",
    "_json_ready",
    "_save_message",
]
