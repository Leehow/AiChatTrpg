"""Async lifecycle operations for committed TRPG memories.

These functions are for player corrections, GM rewrites, and rollback tools.
They update TRPGMemoryItem rows and write TRPGMemoryRevision audit rows.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, TRPGMemoryItem, TRPGMemoryRevision
from services.trpg_memory.memory_models import MemoryStatus
from services.trpg_memory.runtime_store import _item_from_row, memory_item_to_dict


async def invalidate_memory(
    db: AsyncSession,
    session: GameSession,
    *,
    memory_id: str,
    turn_id: str,
    reason: str,
) -> bool:
    row = await _get_memory_row(db, session.id, memory_id)
    if row is None:
        return False
    before = memory_item_to_dict(_item_from_row(row))
    row.status = MemoryStatus.INVALIDATED.value
    row.invalidated_by_turn_id = turn_id
    row.correction_reason = reason
    await _write_revision(db, session, row, turn_id=turn_id, operation="invalidate", reason=reason, before=before)
    await db.flush()
    return True


async def supersede_memory(
    db: AsyncSession,
    session: GameSession,
    *,
    old_memory_id: str,
    new_memory_id: str,
    turn_id: str,
    reason: str,
) -> bool:
    row = await _get_memory_row(db, session.id, old_memory_id)
    if row is None:
        return False
    before = memory_item_to_dict(_item_from_row(row))
    row.status = MemoryStatus.SUPERSEDED.value
    row.superseded_by = new_memory_id
    row.invalidated_by_turn_id = turn_id
    row.correction_reason = reason
    await _write_revision(db, session, row, turn_id=turn_id, operation="supersede", reason=reason, before=before)
    await db.flush()
    return True


async def rollback_memories_by_turn(
    db: AsyncSession,
    session: GameSession,
    *,
    source_turn_ids: Iterable[str],
    rollback_turn_id: str,
    reason: str,
) -> int:
    turns = {str(t) for t in source_turn_ids if str(t)}
    if not turns:
        return 0
    rows = list((await db.execute(
        select(TRPGMemoryItem)
        .where(TRPGMemoryItem.session_id == session.id)
        .where(TRPGMemoryItem.status == MemoryStatus.ACTIVE.value)
    )).scalars().all())
    count = 0
    for row in rows:
        row_turns = {str(t) for t in (row.source_turn_ids_json or [])}
        if not turns.intersection(row_turns):
            continue
        before = memory_item_to_dict(_item_from_row(row))
        row.status = MemoryStatus.ROLLED_BACK.value
        row.invalidated_by_turn_id = rollback_turn_id
        row.correction_reason = reason
        await _write_revision(db, session, row, turn_id=rollback_turn_id, operation="rollback", reason=reason, before=before)
        count += 1
    if count:
        await db.flush()
    return count


async def _get_memory_row(db: AsyncSession, session_id: str, memory_id: str) -> TRPGMemoryItem | None:
    return (await db.execute(
        select(TRPGMemoryItem)
        .where(TRPGMemoryItem.session_id == session_id)
        .where(TRPGMemoryItem.memory_id == memory_id)
        .limit(1)
    )).scalar_one_or_none()


async def _write_revision(
    db: AsyncSession,
    session: GameSession,
    row: TRPGMemoryItem,
    *,
    turn_id: str,
    operation: str,
    reason: str,
    before: dict[str, Any],
) -> None:
    after = memory_item_to_dict(_item_from_row(row))
    db.add(TRPGMemoryRevision(
        memory_id=row.memory_id,
        session_id=session.id,
        campaign_id=row.campaign_id or session.id,
        turn_id=turn_id,
        operation=operation,
        reason=reason,
        before_json=before,
        after_json=after,
    ))
