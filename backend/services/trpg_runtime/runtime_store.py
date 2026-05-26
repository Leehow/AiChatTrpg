"""Async persistence helpers for runtime turn traces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, TRPGTurnTrace
from services.trpg_runtime.turn_trace import TurnTrace


async def save_turn_trace(
    db: AsyncSession,
    session: GameSession,
    trace: TurnTrace,
) -> TRPGTurnTrace:
    """Upsert a turn trace for one session-local turn id."""

    existing = (
        await db.execute(
            select(TRPGTurnTrace)
            .where(TRPGTurnTrace.session_id == session.id)
            .where(TRPGTurnTrace.turn_id == trace.turn_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    row = existing or TRPGTurnTrace(
        session_id=session.id,
        campaign_id=trace.campaign_id or session.id,
        turn_id=trace.turn_id,
    )
    row.campaign_id = trace.campaign_id or session.id
    row.player_input = trace.player_input or ""
    row.context_cache_key = trace.context_cache_key or ""
    row.context_prefix_hash = trace.context_prefix_hash or ""
    row.retrieved_context_block_ids_json = list(trace.retrieved_context_block_ids)
    row.visibility_signature = trace.visibility_signature or ""
    row.model_raw_output_json = _json_object(trace.model_raw_output)
    row.parsed_contract_summary_json = dict(trace.parsed_contract_summary or {})
    row.state_change_ids_json = list(trace.state_change_ids)
    row.memory_proposal_count = int(trace.memory_proposal_count or 0)
    row.committed_memory_ids_json = list(trace.committed_memory_ids)
    row.rejected_memory_count = int(trace.rejected_memory_count or 0)
    row.audit_warnings_json = [dict(item) for item in (trace.audit_warnings or ())]
    row.cache_metrics_json = dict(trace.cache_metrics or {})
    if existing is None:
        db.add(row)
    await db.flush()
    return row


async def list_turn_traces(
    db: AsyncSession,
    session_id: str,
    *,
    limit: int = 50,
    before_id: str | None = None,
) -> tuple[list[TRPGTurnTrace], bool]:
    """Return newest-first trace rows plus a has_more flag."""

    where_clauses = [TRPGTurnTrace.session_id == session_id]
    if before_id:
        anchor = (
            await db.execute(
                select(TRPGTurnTrace.created_at, TRPGTurnTrace.id)
                .where(TRPGTurnTrace.session_id == session_id)
                .where(TRPGTurnTrace.id == before_id)
            )
        ).first()
        if anchor is not None:
            anchor_ts, anchor_id = anchor
            where_clauses.append(
                or_(
                    TRPGTurnTrace.created_at < anchor_ts,
                    and_(
                        TRPGTurnTrace.created_at == anchor_ts,
                        TRPGTurnTrace.id < anchor_id,
                    ),
                )
            )

    capped = max(1, min(limit, 200))
    stmt = (
        select(TRPGTurnTrace)
        .where(*where_clauses)
        .order_by(TRPGTurnTrace.created_at.desc(), TRPGTurnTrace.id.desc())
        .limit(capped + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows[:capped], len(rows) > capped


def trace_row_to_dict(row: TRPGTurnTrace) -> dict[str, Any]:
    return {
        "id": row.id,
        "turn_id": row.turn_id,
        "session_id": row.session_id,
        "campaign_id": row.campaign_id,
        "player_input": row.player_input,
        "context_cache_key": row.context_cache_key,
        "context_prefix_hash": row.context_prefix_hash,
        "retrieved_context_block_ids": row.retrieved_context_block_ids_json or [],
        "visibility_signature": row.visibility_signature,
        "model_raw_output": row.model_raw_output_json or {},
        "parsed_contract_summary": row.parsed_contract_summary_json or {},
        "state_change_ids": row.state_change_ids_json or [],
        "memory_proposal_count": row.memory_proposal_count,
        "committed_memory_ids": row.committed_memory_ids_json or [],
        "rejected_memory_count": row.rejected_memory_count,
        "audit_warnings": row.audit_warnings_json or [],
        "cache_metrics": row.cache_metrics_json or {},
        "created_at": row.created_at,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": value}
