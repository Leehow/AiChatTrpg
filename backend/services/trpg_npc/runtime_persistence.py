"""Database persistence for NPC Runtime V2.

Phase 6 started as dual-write; the table-authority path now writes normalized
runtime rows first and hydrates the JSON snapshot as a compatibility projection.

This module is the public facade.  Helper modules carry the row-building,
hydration, DB upsert, pre-turn rebuild, and snapshot-projection logic so the
facade stays within the 600-line file-size policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import (
    GameSession,
    Message,
    NPCRuntimeActionCard,
    NPCRuntimeEvent,
    NPCRuntimeMemory,
    NPCRuntimeProfile,
    NPCRuntimeRelationship,
    NPCRuntimeState,
)
from orm.models.base import utcnow
from services.trpg_npc.runtime_adapter import (
    NPCActionBoardWarmResult,
    NPCPreTurnRuntimeResult,
    _adapt_npc,
    _current_scene_key,
)
from services.trpg_npc.runtime_persistence_db import (
    _prune_replaced_action_cards,
    _upsert_many,
    _upsert_many_if_column_gte,
)
from services.trpg_npc.runtime_persistence_pre_turn import (
    build_npc_pre_turn_runtime_from_table_rows,
)
from services.trpg_npc.runtime_persistence_rows import (
    _action_card_row,
    _event_row,
    _events_from_message_metadata,
    _iter_action_board_cards,
    _iter_action_board_cards_from_board,
    _memory_row,
    _memory_row_from_dict,
    _profile_row,
    _relationship_row,
    _relationship_row_from_dict,
    _state_row,
)
from services.trpg_npc.runtime_persistence_snapshot import (
    apply_npc_runtime_v2_table_snapshot_to_session,
)


__all__ = [
    "NPCRuntimeTablePayload",
    "apply_npc_runtime_v2_table_snapshot_to_session",
    "build_npc_pre_turn_runtime_from_table_rows",
    "build_npc_pre_turn_runtime_from_tables",
    "build_npc_runtime_v2_table_payloads",
    "build_npc_runtime_v2_table_payloads_from_session_snapshot",
    "hydrate_npc_runtime_v2_from_tables",
    "persist_npc_runtime_v2_table_payload",
    "persist_npc_runtime_v2_tables",
    "persist_npc_runtime_v2_tables_authority",
]


@dataclass(slots=True)
class NPCRuntimeTablePayload:
    profiles: list[dict[str, Any]] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    action_cards: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "profiles": len(self.profiles),
            "states": len(self.states),
            "relationships": len(self.relationships),
            "memories": len(self.memories),
            "action_cards": len(self.action_cards),
            "events": len(self.events),
        }


def build_npc_runtime_v2_table_payloads(
    session: GameSession,
    warm_result: NPCActionBoardWarmResult,
) -> NPCRuntimeTablePayload:
    """Build table-ready rows from a post-turn warm result.

    The function is intentionally pure: useful for debug tests and for future
    backfill scripts that will replay JSON snapshots into proper tables.
    """

    payload = NPCRuntimeTablePayload()
    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        return payload

    now = utcnow()
    for profile in warm_result.profiles_by_id.values():
        payload.profiles.append(_profile_row(session_id, profile, now=now))

    post = warm_result.post_turn
    if post is not None:
        for state in post.updated_states.values():
            payload.states.append(_state_row(session_id, state, now=now))
        for npc_id, relationships in post.updated_relationships.items():
            for target_id, relationship in relationships.items():
                if target_id and target_id != npc_id:
                    payload.relationships.append(
                        _relationship_row(
                            session_id,
                            npc_id,
                            target_id,
                            relationship,
                            now=now,
                        )
                    )
        for memory in post.new_memories:
            payload.memories.append(_memory_row(session_id, memory, now=now))

    board_cards = (
        _iter_action_board_cards_from_board(warm_result.action_board)
        if warm_result.action_board is not None
        else _iter_action_board_cards(session)
    )
    for scene_id, card in board_cards:
        payload.action_cards.append(_action_card_row(session_id, scene_id, card, now=now))

    for event in warm_result.committed_events:
        payload.events.append(_event_row(session_id, event, now=now))

    return payload


def build_npc_runtime_v2_table_payloads_from_session_snapshot(
    session: GameSession,
    *,
    messages: list[Message] | None = None,
    include_inferred_state: bool = False,
) -> NPCRuntimeTablePayload:
    """Build table payloads from existing JSON snapshots.

    Used by backfill. Profiles are inferred from current NPC JSON; state,
    relationships, and memories are only taken from V2 subdocuments unless
    `include_inferred_state` is enabled.
    """

    payload = NPCRuntimeTablePayload()
    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        return payload

    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    scene_id = _current_scene_key(session) or "scene_unknown"
    now = utcnow()
    if isinstance(npcs, list):
        for npc in npcs:
            if not isinstance(npc, dict):
                continue
            try:
                profile, state, _rel = _adapt_npc(npc, scene_id=scene_id)
            except Exception:
                continue
            payload.profiles.append(_profile_row(session_id, profile, now=now))
            if include_inferred_state or isinstance(npc.get("runtime_state_v2"), dict):
                payload.states.append(_state_row(session_id, state, now=now))
            relationships = npc.get("relationships_v2")
            if isinstance(relationships, dict):
                for target_id, raw in relationships.items():
                    if isinstance(raw, dict) and str(target_id).strip():
                        payload.relationships.append(
                            _relationship_row_from_dict(
                                session_id,
                                profile.npc_id,
                                str(target_id),
                                raw,
                                now=now,
                            )
                        )
            memories = npc.get("memories_v2")
            if isinstance(memories, list):
                for raw_memory in memories:
                    if isinstance(raw_memory, dict) and raw_memory.get("memory_id"):
                        payload.memories.append(
                            _memory_row_from_dict(session_id, profile.npc_id, raw_memory, now=now)
                        )

    for scene_key, card in _iter_action_board_cards(session):
        payload.action_cards.append(_action_card_row(session_id, scene_key, card, now=now))

    for event in _events_from_message_metadata(messages or []):
        payload.events.append(_event_row(session_id, event, now=now))

    return payload


async def persist_npc_runtime_v2_tables(
    db: AsyncSession,
    session: GameSession,
    warm_result: NPCActionBoardWarmResult,
) -> dict[str, Any]:
    """Dual-write Runtime V2 artifacts into normalized tables.

    Caller owns the transaction and commit. Failures should be caught by the
    caller so a table-write issue never breaks the visible IC turn.
    """

    payload = build_npc_runtime_v2_table_payloads(session, warm_result)
    summary: dict[str, Any] = payload.summary()
    if not any(summary.values()):
        summary["skipped_reason"] = "empty_payload"
        return summary

    await persist_npc_runtime_v2_table_payload(db, payload)
    return summary


async def persist_npc_runtime_v2_tables_authority(
    db: AsyncSession,
    session: GameSession,
    warm_result: NPCActionBoardWarmResult,
    *,
    memory_cap: int = 20,
) -> dict[str, Any]:
    """Persist Runtime V2 artifacts with normalized tables as the authority.

    Mutable rows use monotonic guards so an older turn cannot overwrite newer
    NPC state or ActionBoard cards. After the table write, the JSON fields on
    `session.memory_state` are refreshed from the table rows as a compatibility
    snapshot for older code paths.
    """

    payload = build_npc_runtime_v2_table_payloads(session, warm_result)
    summary: dict[str, Any] = payload.summary()
    summary["authority"] = "tables"
    if not any(value for value in summary.values() if isinstance(value, int)):
        summary["skipped_reason"] = "empty_payload"
        return summary

    summary["profiles_affected"] = await _upsert_many(
        db, NPCRuntimeProfile.__table__, payload.profiles, ["id"],
    )
    summary["states_affected"] = await _upsert_many_if_column_gte(
        db,
        NPCRuntimeState.__table__,
        payload.states,
        ["id"],
        "state_version",
    )
    summary["relationships_affected"] = await _upsert_many(
        db, NPCRuntimeRelationship.__table__, payload.relationships, ["id"],
    )
    summary["memories_affected"] = await _upsert_many(
        db, NPCRuntimeMemory.__table__, payload.memories, ["memory_id"],
    )
    summary["action_cards_affected"] = await _upsert_many_if_column_gte(
        db,
        NPCRuntimeActionCard.__table__,
        payload.action_cards,
        ["card_id"],
        "based_on_turn_id",
    )
    keep_current_scene_card_ids = {
        str(row.get("card_id") or "")
        for row in payload.action_cards
        if str(row.get("scene_id") or "") == warm_result.scene_id
    }
    summary["action_cards_pruned"] = await _prune_replaced_action_cards(
        db,
        session_id=str(getattr(session, "id", "") or ""),
        scene_id=warm_result.scene_id,
        keep_card_ids=keep_current_scene_card_ids,
        through_turn_id=warm_result.turn_id,
    )
    summary["events_affected"] = await _upsert_many(
        db, NPCRuntimeEvent.__table__, payload.events, ["event_id"],
    )
    summary["json_snapshot"] = await hydrate_npc_runtime_v2_from_tables(
        db,
        session,
        memory_cap=memory_cap,
        current_turn=warm_result.turn_id,
        current_scene_id=warm_result.scene_id,
    )
    return summary


async def persist_npc_runtime_v2_table_payload(
    db: AsyncSession,
    payload: NPCRuntimeTablePayload,
) -> None:
    """Upsert a pre-built Runtime V2 table payload."""

    await _upsert_many(db, NPCRuntimeProfile.__table__, payload.profiles, ["id"])
    await _upsert_many(db, NPCRuntimeState.__table__, payload.states, ["id"])
    await _upsert_many(db, NPCRuntimeRelationship.__table__, payload.relationships, ["id"])
    await _upsert_many(db, NPCRuntimeMemory.__table__, payload.memories, ["memory_id"])
    await _upsert_many(db, NPCRuntimeActionCard.__table__, payload.action_cards, ["card_id"])
    await _upsert_many(db, NPCRuntimeEvent.__table__, payload.events, ["event_id"])


async def hydrate_npc_runtime_v2_from_tables(
    db: AsyncSession,
    session: GameSession,
    *,
    memory_cap: int = 20,
    current_turn: int | None = None,
    current_scene_id: str | None = None,
) -> dict[str, Any]:
    """Hydrate table-backed V2 data into the current JSON session snapshot.

    Current foreground adapters are synchronous and read `session.memory_state`.
    Hydrating lets us prefer table data without rewriting that whole path yet.
    Missing table rows leave existing JSON untouched.
    """

    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        return {"skipped_reason": "missing_session_id"}

    states = list((
        await db.execute(
            select(NPCRuntimeState).where(NPCRuntimeState.session_id == session_id)
        )
    ).scalars().all())
    relationships = list((
        await db.execute(
            select(NPCRuntimeRelationship).where(NPCRuntimeRelationship.session_id == session_id)
        )
    ).scalars().all())
    memories = list((
        await db.execute(
            select(NPCRuntimeMemory)
            .where(NPCRuntimeMemory.session_id == session_id)
            .order_by(NPCRuntimeMemory.created_at.asc())
        )
    ).scalars().all())
    action_cards = list((
        await db.execute(
            select(NPCRuntimeActionCard).where(NPCRuntimeActionCard.session_id == session_id)
        )
    ).scalars().all())

    return apply_npc_runtime_v2_table_snapshot_to_session(
        session,
        states=states,
        relationships=relationships,
        memories=memories,
        action_cards=action_cards,
        memory_cap=memory_cap,
        current_turn=current_turn,
        current_scene_id=current_scene_id,
    )


async def build_npc_pre_turn_runtime_from_tables(
    db: AsyncSession,
    session: GameSession,
    *,
    player_text: str,
    active_npcs: list[dict[str, Any]] | None = None,
    turn_id: int | None = None,
    actor_id: str = "pc",
) -> NPCPreTurnRuntimeResult:
    """Run pre-turn using Runtime V2 tables as the authoritative source.

    Falls back internally to JSON-derived profiles/states for NPCs that do not
    yet have table rows. The function does not mutate session JSON.
    """

    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        result = NPCPreTurnRuntimeResult()
        result.error = "missing_session_id"
        return result

    npc_ids = [
        str(npc.get("key") or "").strip()
        for npc in active_npcs or []
        if isinstance(npc, dict) and str(npc.get("key") or "").strip()
    ]
    profile_rows = list((
        await db.execute(
            select(NPCRuntimeProfile).where(NPCRuntimeProfile.session_id == session_id)
        )
    ).scalars().all())
    state_rows = list((
        await db.execute(
            select(NPCRuntimeState).where(NPCRuntimeState.session_id == session_id)
        )
    ).scalars().all())
    relationship_rows = list((
        await db.execute(
            select(NPCRuntimeRelationship).where(NPCRuntimeRelationship.session_id == session_id)
        )
    ).scalars().all())
    action_card_rows = list((
        await db.execute(
            select(NPCRuntimeActionCard).where(NPCRuntimeActionCard.session_id == session_id)
        )
    ).scalars().all())
    if npc_ids:
        profile_rows = [row for row in profile_rows if row.npc_id in npc_ids]
        state_rows = [row for row in state_rows if row.npc_id in npc_ids]
        relationship_rows = [row for row in relationship_rows if row.npc_id in npc_ids]

    return build_npc_pre_turn_runtime_from_table_rows(
        session,
        player_text=player_text,
        active_npcs=active_npcs,
        turn_id=turn_id,
        actor_id=actor_id,
        profile_rows=profile_rows,
        state_rows=state_rows,
        relationship_rows=relationship_rows,
        action_card_rows=action_card_rows,
    )
