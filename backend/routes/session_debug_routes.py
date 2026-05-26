"""Debug / runtime-inspection routes for `/api/sessions/{session_id}/...`.

Extracted from `routes/sessions.py` so the main router file can focus on
session CRUD, character/adventure setup, and messages. This subrouter is
mounted via `router.include_router(session_debug_router)` from `sessions.py`
at the original cluster location, so route paths, response models, query
parameters, auth dependencies, and payload shapes are unchanged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import (
    CheckLog,
    NPCRuntimeActionCard,
    NPCRuntimeEvent,
    NPCRuntimeMemory,
    NPCRuntimeProfile,
    NPCRuntimeRelationship,
    NPCRuntimeState,
    TRPGMemoryItem,
    TRPGStateChange,
    TRPGTurnTrace,
    TRPGWorldStateSnapshot,
    User,
)
from routes.deps import current_user, db_session
from routes.session_helpers import (
    _check_log_out,
    _count_session_rows,
    _get_owned_session,
    _memory_item_debug_out,
    _npc_runtime_action_board,
    _npc_runtime_action_card_payload,
    _npc_runtime_planner_runs,
    _state_change_debug_out,
    _turn_trace_out,
)
from schemas.session import (
    CheckLogListResponse,
    NpcRuntimeDebugOut,
    PublicMemoryViewOut,
    TurnTraceListResponse,
)
from services.trpg_memory.runtime_store import (
    build_public_memory_view,
    public_memory_view_to_dict,
)
from services.trpg_runtime.runtime_store import list_turn_traces


session_debug_router = APIRouter()


@session_debug_router.get(
    "/{session_id}/check-logs", response_model=CheckLogListResponse,
)
async def list_check_logs(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CheckLogListResponse:
    """Return recent replayable CHECK logs for the debug panel."""

    await _get_owned_session(db, session_id, user)
    total_stmt = select(func.count()).select_from(CheckLog).where(
        CheckLog.session_id == session_id
    )
    total = int((await db.execute(total_stmt)).scalar() or 0)

    where_clauses = [CheckLog.session_id == session_id]
    if before_id:
        anchor = (
            await db.execute(
                select(CheckLog.created_at, CheckLog.id).where(
                    CheckLog.id == before_id,
                    CheckLog.session_id == session_id,
                )
            )
        ).first()
        if anchor is None:
            raise HTTPException(404, "before_id not found in this session")
        anchor_ts, anchor_id = anchor
        where_clauses.append(
            or_(
                CheckLog.created_at < anchor_ts,
                and_(
                    CheckLog.created_at == anchor_ts,
                    CheckLog.id < anchor_id,
                ),
            )
        )

    stmt = (
        select(CheckLog)
        .where(*where_clauses)
        .order_by(CheckLog.created_at.desc(), CheckLog.id.desc())
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    return CheckLogListResponse(
        items=[_check_log_out(row) for row in rows],
        total=total,
        has_more=has_more,
    )


@session_debug_router.get(
    "/{session_id}/turn-traces", response_model=TurnTraceListResponse,
)
async def list_runtime_turn_traces(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> TurnTraceListResponse:
    """Return recent Runtime v2 turn traces for replay/debug panels."""

    await _get_owned_session(db, session_id, user)
    total_stmt = select(func.count()).select_from(TRPGTurnTrace).where(
        TRPGTurnTrace.session_id == session_id
    )
    total = int((await db.execute(total_stmt)).scalar() or 0)
    rows, has_more = await list_turn_traces(
        db,
        session_id,
        limit=limit,
        before_id=before_id,
    )
    return TurnTraceListResponse(
        items=[_turn_trace_out(row) for row in rows],
        total=total,
        has_more=has_more,
    )


@session_debug_router.get(
    "/{session_id}/memory-public-view", response_model=PublicMemoryViewOut,
)
async def get_memory_public_view(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PublicMemoryViewOut:
    """Return the player-safe projection of committed runtime memories."""

    await _get_owned_session(db, session_id, user)
    view = await build_public_memory_view(db, session_id)
    return PublicMemoryViewOut(**public_memory_view_to_dict(view))


@session_debug_router.get("/{session_id}/memory-items-debug")
async def list_memory_items_debug(
    session_id: str,
    visibility: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Return raw runtime memory rows for automated tests/debug panels."""

    await _get_owned_session(db, session_id, user)
    stmt = select(TRPGMemoryItem).where(TRPGMemoryItem.session_id == session_id)
    if visibility:
        stmt = stmt.where(TRPGMemoryItem.visibility == visibility)
    if kind:
        stmt = stmt.where(TRPGMemoryItem.kind == kind)
    if not include_inactive:
        stmt = stmt.where(TRPGMemoryItem.status == "active")
    stmt = stmt.order_by(TRPGMemoryItem.created_at.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return {"items": [_memory_item_debug_out(row) for row in rows], "count": len(rows)}


@session_debug_router.get("/{session_id}/state-changes-debug")
async def list_state_changes_debug(
    session_id: str,
    turn_id: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Return canonical state changes for automated runtime assertions."""

    await _get_owned_session(db, session_id, user)
    stmt = select(TRPGStateChange).where(TRPGStateChange.session_id == session_id)
    if turn_id:
        stmt = stmt.where(TRPGStateChange.turn_id == turn_id)
    if visibility:
        stmt = stmt.where(TRPGStateChange.visibility == visibility)
    stmt = stmt.order_by(TRPGStateChange.created_at.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return {"items": [_state_change_debug_out(row) for row in rows], "count": len(rows)}


@session_debug_router.get("/{session_id}/world-state-debug")
async def get_world_state_debug(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Return the latest authoritative world-state snapshot for debugging."""

    await _get_owned_session(db, session_id, user)
    row = (
        await db.execute(
            select(TRPGWorldStateSnapshot)
            .where(TRPGWorldStateSnapshot.session_id == session_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"exists": False, "state": {}, "version": 0}
    return {
        "exists": True,
        "campaign_id": row.campaign_id,
        "version": row.version,
        "state": row.state_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@session_debug_router.get(
    "/{session_id}/npc-runtime-debug", response_model=NpcRuntimeDebugOut,
)
async def get_npc_runtime_debug(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> NpcRuntimeDebugOut:
    """Return NPC Runtime V2 table-backed diagnostics for the debug panel."""

    await _get_owned_session(db, session_id, user)
    counts = {
        "profiles": await _count_session_rows(db, NPCRuntimeProfile, session_id),
        "states": await _count_session_rows(db, NPCRuntimeState, session_id),
        "relationships": await _count_session_rows(
            db,
            NPCRuntimeRelationship,
            session_id,
        ),
        "memories": await _count_session_rows(db, NPCRuntimeMemory, session_id),
        "action_cards": await _count_session_rows(db, NPCRuntimeActionCard, session_id),
        "events": await _count_session_rows(db, NPCRuntimeEvent, session_id),
    }
    cards = list((
        await db.execute(
            select(NPCRuntimeActionCard)
            .where(NPCRuntimeActionCard.session_id == session_id)
            .order_by(
                NPCRuntimeActionCard.based_on_turn_id.desc(),
                NPCRuntimeActionCard.priority.desc(),
                NPCRuntimeActionCard.card_id.asc(),
            )
            .limit(limit)
        )
    ).scalars().all())
    runs = _npc_runtime_planner_runs(cards, counts=counts)
    action_board = _npc_runtime_action_board(cards)
    events = list((
        await db.execute(
            select(NPCRuntimeEvent)
            .where(NPCRuntimeEvent.session_id == session_id)
            .order_by(NPCRuntimeEvent.turn_id.desc(), NPCRuntimeEvent.event_id.asc())
            .limit(50)
        )
    ).scalars().all())
    memories = list((
        await db.execute(
            select(NPCRuntimeMemory)
            .where(NPCRuntimeMemory.session_id == session_id)
            .order_by(NPCRuntimeMemory.importance.desc(), NPCRuntimeMemory.memory_id.asc())
            .limit(30)
        )
    ).scalars().all())
    return NpcRuntimeDebugOut(
        counts=counts,
        planner_latest=runs[-1] if runs else {},
        planner_runs=runs,
        action_board=action_board,
        action_cards=[_npc_runtime_action_card_payload(card) for card in cards],
        events=[
            {
                "event_id": event.event_id,
                "scene_id": event.scene_id,
                "turn_id": event.turn_id,
                "type": event.type,
                "actor_id": event.actor_id,
                "target_ids": event.target_ids_json or [],
                "payload": event.payload_json or {},
                "visibility": event.visibility_json or {},
                "event": event.event_json or {},
                "created_at": event.created_at.isoformat() if event.created_at else "",
            }
            for event in events
        ],
        sample_memories=[
            {
                "memory_id": memory.memory_id,
                "npc_id": memory.npc_id,
                "memory_type": memory.memory_type,
                "content": memory.content,
                "importance": memory.importance,
                "source_event_ids": memory.source_event_ids_json or [],
                "tags": memory.tags_json or [],
                "memory": memory.memory_json or {},
                "created_at": memory.created_at.isoformat() if memory.created_at else "",
            }
            for memory in memories
        ],
    )
