"""Per-message post-processing step tracker.

Records a timeline of what the post-visible pipeline is doing for a given
GM message so the frontend can display progress + timing under the
chat bubble (mirrors chatlab's ``TrpgPostprocessDebug`` UI).

Each event is appended to ``messages.metadata_json["postprocess_steps"]``
as a list of dicts::

    {"type": "postprocess_step",
     "name":   <stable identifier, e.g. "npc_text_sync">,
     "status": "running" | "done",
     "duration_ms": int,
     "detail": "<short summary>",
     "ts":     "<ISO-8601 UTC>"}

Two usage patterns:

1. **Inline (sync caller already has a db)** — instantaneous events:

       await record_step(db, message_id, "spoken_npcs", detail="2 created")

   …or paired running/done with timing via the context manager:

       async with step_timer_with_db(db, message_id, "markers"):
           apply_chatrpg_markers(...)

2. **Background (fire-and-forget task; no shared db)** — the helper
   opens its own short-lived session per write::

       async with step_timer(message_id, "npc_text_sync"):
           await sync_npcs_after_turn(...)

Both patterns row-lock the underlying ``messages`` row during
read-modify-write so concurrent background tasks don't lose entries
when they all want to append.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.database import get_session_factory
from orm.models import Message

logger = logging.getLogger("chatrpg.trpg_postprocess_steps")

PHASE_COMPLETE_NAME = "phase3_complete"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_event(
    name: str,
    *,
    status: str,
    duration_ms: int,
    detail: str,
) -> dict[str, Any]:
    return {
        "type": "postprocess_step",
        "name": str(name),
        "status": str(status),
        "duration_ms": int(duration_ms),
        "detail": str(detail or "")[:240],
        "ts": _now_iso(),
    }


async def _append_under_lock(
    db: AsyncSession,
    message_id: str,
    event: dict[str, Any],
) -> None:
    """Read-modify-write the message's ``metadata_json["postprocess_steps"]``
    array under a SELECT FOR UPDATE row lock so concurrent background
    tasks all land their events instead of clobbering each other."""
    stmt = select(Message).where(Message.id == message_id).with_for_update()
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        return
    md = dict(msg.metadata_json or {})
    steps = list(md.get("postprocess_steps") or [])
    steps.append(event)
    md["postprocess_steps"] = steps
    if event.get("name") == PHASE_COMPLETE_NAME and event.get("status") == "done":
        md["postprocess_done"] = True
    msg.metadata_json = md
    flag_modified(msg, "metadata_json")
    await db.commit()


async def record_step(
    db: AsyncSession,
    message_id: str,
    name: str,
    *,
    status: str = "done",
    duration_ms: int = 0,
    detail: str = "",
) -> None:
    """Append one step event to the message's timeline using the caller's db.

    Failures are swallowed and logged — step recording must never break
    the surrounding pipeline.
    """
    if not message_id:
        return
    try:
        await _append_under_lock(
            db,
            message_id,
            _make_event(
                name, status=status, duration_ms=int(duration_ms), detail=detail
            ),
        )
    except Exception as exc:  # noqa: BLE001 - never break the turn
        logger.warning(
            "[postprocess_steps] record failed name=%s msg=%s: %s",
            name, message_id, exc,
        )


async def record_step_standalone(
    message_id: str,
    name: str,
    *,
    status: str = "done",
    duration_ms: int = 0,
    detail: str = "",
) -> None:
    """Same as :func:`record_step` but opens its own DB session — for use
    inside fire-and-forget background tasks that have no shared db."""
    if not message_id:
        return
    factory = get_session_factory()
    try:
        async with factory() as db:
            await record_step(
                db, message_id, name, status=status,
                duration_ms=duration_ms, detail=detail,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[postprocess_steps] standalone record failed name=%s msg=%s: %s",
            name, message_id, exc,
        )


@asynccontextmanager
async def step_timer_with_db(
    db: AsyncSession,
    message_id: str,
    name: str,
    *,
    detail: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Inline running→done pair using the caller's ``db``. Returns a
    handle dict so the caller can mutate ``handle["detail"]`` after the
    work runs to surface a real result string.
    """
    handle: dict[str, Any] = {"detail": detail}
    started = time.monotonic()
    if message_id:
        await record_step(db, message_id, name, status="running", detail=detail)
    try:
        yield handle
    finally:
        if message_id:
            duration_ms = int((time.monotonic() - started) * 1000)
            await record_step(
                db, message_id, name,
                status="done",
                duration_ms=duration_ms,
                detail=handle.get("detail") or detail,
            )


@asynccontextmanager
async def step_timer(
    message_id: str,
    name: str,
    *,
    detail: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Background-friendly running→done pair that owns its own DB
    sessions. Use inside ``asyncio.create_task``-style fire-and-forget
    workers where ``db`` is not threaded through.
    """
    handle: dict[str, Any] = {"detail": detail}
    started = time.monotonic()
    await record_step_standalone(message_id, name, status="running", detail=detail)
    try:
        yield handle
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        await record_step_standalone(
            message_id, name,
            status="done",
            duration_ms=duration_ms,
            detail=handle.get("detail") or detail,
        )


async def mark_phase_complete(
    message_id: str,
    *,
    duration_ms: int = 0,
    detail: str = "",
) -> None:
    """Final summary event. Frontend treats this as the signal to stop
    polling. Idempotent — duplicate calls are harmless (frontend dedupes
    by name)."""
    await record_step_standalone(
        message_id,
        PHASE_COMPLETE_NAME,
        status="done",
        duration_ms=duration_ms,
        detail=detail,
    )


async def fetch_steps(
    db: AsyncSession,
    message_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Read the persisted timeline for a message. Returns
    ``(steps, done)`` where ``done`` is True once a ``phase3_complete``
    event has been recorded."""
    msg = await db.get(Message, message_id)
    if msg is None:
        return [], False
    md = msg.metadata_json or {}
    steps = list(md.get("postprocess_steps") or [])
    done = bool(md.get("postprocess_done")) or any(
        isinstance(s, dict)
        and s.get("name") == PHASE_COMPLETE_NAME
        and s.get("status") == "done"
        for s in steps
    )
    return steps, done


# A best-effort barrier the IC runner uses to schedule the
# `phase3_complete` event after every background task it spawns has had
# a chance to record its own events. Each spawn registers a future here
# and resolves it from inside its `step_timer` exit.
class PhaseTracker:
    """Track outstanding background work for a message so we know when
    all post-visible tasks have settled and ``phase3_complete`` can
    fire. Lifecycle: register one tracker per assistant message, call
    ``add_task`` for each fire-and-forget task, then ``await
    wait_and_complete()`` from a fresh fire-and-forget coroutine that
    finalises the timeline.
    """

    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self._tasks: list[asyncio.Task] = []
        self._started = time.monotonic()

    def add_task(self, task: asyncio.Task) -> None:
        if task is not None:
            self._tasks.append(task)

    async def wait_and_complete(self, *, detail: str = "") -> None:
        """Awaits all registered tasks (errors swallowed individually),
        then writes ``phase3_complete``. Safe to call without any
        registered tasks — emits an immediate completion event with
        ``duration_ms=0`` so the frontend stops polling."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        duration_ms = int((time.monotonic() - self._started) * 1000)
        await mark_phase_complete(
            self.message_id, duration_ms=duration_ms, detail=detail,
        )
