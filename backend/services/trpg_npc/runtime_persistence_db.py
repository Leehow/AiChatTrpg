"""Async database upsert/prune helpers for NPC Runtime V2 persistence.

These helpers wrap PostgreSQL `INSERT ... ON CONFLICT` and conditional
upserts used by the table-authority persistence path.  Splitting them off
keeps the public `runtime_persistence` module focused on orchestration.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import NPCRuntimeActionCard
from services.trpg_npc.runtime_persistence_helpers import _result_rowcount


async def _upsert_many(
    db: AsyncSession,
    table,
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(table).values(rows)
    excluded = stmt.excluded
    update_columns = {
        column.name: getattr(excluded, column.name)
        for column in table.columns
        if column.name not in set(conflict_cols) | {"created_at"}
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c[name] for name in conflict_cols],
        set_=update_columns,
    )
    result = await db.execute(stmt)
    return _result_rowcount(result, fallback=len(rows))


async def _upsert_many_if_column_gte(
    db: AsyncSession,
    table,
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
    column_name: str,
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(table).values(rows)
    excluded = stmt.excluded
    update_columns = {
        column.name: getattr(excluded, column.name)
        for column in table.columns
        if column.name not in set(conflict_cols) | {"created_at"}
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c[name] for name in conflict_cols],
        set_=update_columns,
        where=getattr(excluded, column_name) >= table.c[column_name],
    )
    result = await db.execute(stmt)
    return _result_rowcount(result, fallback=len(rows))


async def _prune_replaced_action_cards(
    db: AsyncSession,
    *,
    session_id: str,
    scene_id: str,
    keep_card_ids: set[str],
    through_turn_id: int,
) -> int:
    if not session_id or not scene_id or through_turn_id <= 0:
        return 0
    stmt = delete(NPCRuntimeActionCard).where(
        NPCRuntimeActionCard.session_id == session_id,
        NPCRuntimeActionCard.scene_id == scene_id,
        NPCRuntimeActionCard.based_on_turn_id <= through_turn_id,
    )
    keep = [card_id for card_id in keep_card_ids if card_id]
    if keep:
        stmt = stmt.where(NPCRuntimeActionCard.card_id.notin_(keep))
    result = await db.execute(stmt)
    return _result_rowcount(result, fallback=0)
