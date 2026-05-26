"""Player-triggered relative in-game time advance.

Sibling to the existing absolute setter at
``backend/routes/sessions.py:post_in_game_time`` (``POST /in-game-time``):
this endpoint adds a ``+N minutes`` delta for common quick advances in the
scene HUD. The absolute setter is intentionally untouched — it remains the
drift-correction modal. Full ChatLab world clocks and counter triggers are
out of scope for V1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession, User
from routes.deps import current_user, db_session
from schemas.session import (
    AdvanceInGameTimeRequest,
    ForceInGameTimeResponse,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


_MAX_DELTA_MINUTES = 24 * 60  # ±24h per call, matches the recommended bound.
_DEFAULT_START_CLOCK_MINUTES = 9 * 60  # 09:00, same default used by adventure-start.


def _period_from_hour(hour: int) -> str:
    """Mirror ``backend/routes/sessions.py:_period_from_hour`` so the HUD
    label stays consistent across the absolute and delta endpoints."""
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _clock_to_minutes(clock: Any) -> int | None:
    if not isinstance(clock, str):
        return None
    parts = clock.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _format_clock(total_minutes: int) -> str:
    minute_of_day = total_minutes % (24 * 60)
    hour, minute = divmod(minute_of_day, 60)
    return f"{hour:02d}:{minute:02d}"


def advance_module_state(
    module_state: dict[str, Any], minutes: int,
) -> dict[str, Any]:
    """Advance the in-game clock by ``minutes`` (positive or negative) and
    return the patched ``module_state``. Pure function so it stays
    unit-testable without a DB session.

    Behavior mirrors ``services.trpg_ic_markers.apply_chatrpg_markers``:
    base clock is the current ``in_game_time`` (falling back to 09:00 on day
    1 when uninitialized), ``day_count`` rolls over on 24h overflow, and
    ``elapsed_minutes`` accumulates the absolute delta so the runtime can
    keep tracking session length.
    """
    base_clock = _clock_to_minutes(module_state.get("in_game_time"))
    try:
        day_count = int(module_state.get("day_count") or 1)
    except (TypeError, ValueError):
        day_count = 1
    if day_count < 1:
        day_count = 1
    if base_clock is None:
        base_clock = _DEFAULT_START_CLOCK_MINUTES

    total = base_clock + minutes
    day_overflow, clock_minutes = divmod(total, 24 * 60)
    new_day = day_count + day_overflow
    if new_day < 1:
        new_day = 1

    try:
        prev_elapsed = int(module_state.get("elapsed_minutes") or 0)
    except (TypeError, ValueError):
        prev_elapsed = 0
    next_elapsed = prev_elapsed + abs(minutes)

    clock_str = _format_clock(clock_minutes)
    hour_of_day = clock_minutes // 60

    module_state["in_game_time"] = clock_str
    module_state["in_game_period"] = _period_from_hour(hour_of_day)
    module_state["day_count"] = new_day
    module_state["elapsed_minutes"] = next_elapsed
    return module_state


async def _get_owned_session(
    db: AsyncSession, session_id: str, user: User,
) -> GameSession:
    s = await db.get(GameSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "session not found")
    return s


@router.post(
    "/{session_id}/advance-time",
    response_model=ForceInGameTimeResponse,
)
async def post_advance_time(
    session_id: str,
    body: AdvanceInGameTimeRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> ForceInGameTimeResponse:
    minutes = body.minutes
    if minutes == 0:
        raise HTTPException(400, "minutes must be non-zero")
    if abs(minutes) > _MAX_DELTA_MINUTES:
        raise HTTPException(400, "minutes must be within ±1440 (24h)")

    s = await _get_owned_session(db, session_id, user)
    module_state = dict(s.module_state) if isinstance(s.module_state, dict) else {}
    module_state = advance_module_state(module_state, minutes)

    s.module_state = module_state
    flag_modified(s, "module_state")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)

    refreshed = s.module_state if isinstance(s.module_state, dict) else {}
    return ForceInGameTimeResponse(
        day=int(refreshed.get("day_count") or 1),
        clock=str(refreshed.get("in_game_time") or "09:00"),
        period=str(refreshed.get("in_game_period") or "morning"),
        date=refreshed.get("in_game_date") if isinstance(refreshed.get("in_game_date"), str) else None,
        elapsed_minutes=int(refreshed.get("elapsed_minutes") or 0),
    )
