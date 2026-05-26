"""Row builders, event extraction, and action board iteration helpers.

Pure functions used by `runtime_persistence` to convert domain objects and
session JSON into table-ready row dicts.  Kept separate from the public
persistence API so the facade can stay below the 600-line policy.
"""

from __future__ import annotations

from typing import Any

from orm.models import GameSession, Message
from orm.models.base import utcnow
from services.trpg_npc.action_board import ActionBoard
from services.trpg_npc.models import (
    GameEvent,
    MemoryRecord,
    NPCProfile,
    NPCState,
    RelationshipVector,
)
from services.trpg_npc.runtime_persistence_helpers import (
    _float,
    _int,
    _list_strings,
    _row_id,
)


_ACTION_BOARD_KEY = "_npc_action_board_v2"


def _profile_row(session_id: str, profile: NPCProfile, *, now) -> dict[str, Any]:
    return {
        "id": _row_id(session_id, profile.npc_id),
        "session_id": session_id,
        "npc_id": profile.npc_id,
        "tier": profile.tier.value,
        "profile_json": profile.to_dict(),
        "created_at": now,
        "updated_at": now,
    }


def _state_row(session_id: str, state: NPCState, *, now) -> dict[str, Any]:
    return {
        "id": _row_id(session_id, state.npc_id),
        "session_id": session_id,
        "npc_id": state.npc_id,
        "scene_id": str(state.scene_id or ""),
        "state_version": int(state.state_version or 0),
        "state_json": state.to_dict(),
        "created_at": now,
        "updated_at": now,
    }


def _relationship_row(
    session_id: str,
    npc_id: str,
    target_id: str,
    relationship: RelationshipVector,
    *,
    now,
) -> dict[str, Any]:
    return {
        "id": _row_id(session_id, npc_id, target_id),
        "session_id": session_id,
        "npc_id": npc_id,
        "target_id": target_id,
        "relationship_json": relationship.to_dict(),
        "created_at": now,
        "updated_at": now,
    }


def _relationship_row_from_dict(
    session_id: str,
    npc_id: str,
    target_id: str,
    relationship: dict[str, Any],
    *,
    now,
) -> dict[str, Any]:
    return {
        "id": _row_id(session_id, npc_id, target_id),
        "session_id": session_id,
        "npc_id": npc_id,
        "target_id": target_id,
        "relationship_json": dict(relationship),
        "created_at": now,
        "updated_at": now,
    }


def _memory_row(session_id: str, memory: MemoryRecord, *, now) -> dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "session_id": session_id,
        "npc_id": memory.npc_id,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "importance": float(memory.importance),
        "source_event_ids_json": list(memory.source_event_ids),
        "tags_json": list(memory.tags),
        "memory_json": memory.to_dict(),
        "created_at": now,
        "updated_at": now,
    }


def _memory_row_from_dict(
    session_id: str,
    npc_id: str,
    memory: dict[str, Any],
    *,
    now,
) -> dict[str, Any]:
    return {
        "memory_id": str(memory.get("memory_id") or ""),
        "session_id": session_id,
        "npc_id": str(memory.get("npc_id") or npc_id),
        "memory_type": str(memory.get("memory_type") or "episodic"),
        "content": str(memory.get("content") or ""),
        "importance": _float(memory.get("importance"), default=0.5),
        "source_event_ids_json": _list_strings(memory.get("source_event_ids")),
        "tags_json": _list_strings(memory.get("tags")),
        "memory_json": dict(memory),
        "created_at": now,
        "updated_at": now,
    }


def _action_card_row(
    session_id: str,
    scene_id: str,
    card: dict[str, Any],
    *,
    now,
) -> dict[str, Any]:
    return {
        "card_id": str(card.get("card_id") or ""),
        "session_id": session_id,
        "scene_id": str(scene_id or card.get("scene_id") or ""),
        "npc_id": str(card.get("npc_id") or ""),
        "based_on_turn_id": _int(card.get("based_on_turn_id")),
        "valid_until_turn": _int(card.get("valid_until_turn")),
        "priority": _float(card.get("priority")),
        "status": str(card.get("status") or ""),
        "card_json": dict(card),
        "created_at": now,
        "updated_at": now,
    }


def _event_row(session_id: str, event: GameEvent, *, now) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "session_id": session_id,
        "scene_id": event.scene_id,
        "turn_id": int(event.turn_id or 0),
        "type": event.type,
        "actor_id": str(event.actor_id or ""),
        "target_ids_json": list(event.target_ids),
        "payload_json": dict(event.payload),
        "visibility_json": dict(event.visibility),
        "event_json": event.to_dict(),
        "created_at": now,
        "updated_at": now,
    }


def _events_from_message_metadata(messages: list[Message]) -> list[GameEvent]:
    events: list[GameEvent] = []
    seen: set[str] = set()
    for message in messages:
        meta = getattr(message, "metadata_json", None)
        if not isinstance(meta, dict):
            continue
        payload = meta.get("structured_events")
        if not isinstance(payload, dict):
            continue
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            continue
        for raw in raw_events:
            event = _event_from_dict(raw)
            if event is None or event.event_id in seen:
                continue
            seen.add(event.event_id)
            events.append(event)
    return events


def _event_from_dict(raw: Any) -> GameEvent | None:
    if not isinstance(raw, dict):
        return None
    event_id = str(raw.get("event_id") or "").strip()
    event_type = str(raw.get("type") or "").strip()
    scene_id = str(raw.get("scene_id") or "").strip()
    if not event_id or not event_type or not scene_id:
        return None
    target_ids = _list_strings(raw.get("target_ids"))
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    visibility = raw.get("visibility") if isinstance(raw.get("visibility"), dict) else {}
    return GameEvent(
        event_id=event_id,
        type=event_type,
        scene_id=scene_id,
        turn_id=_int(raw.get("turn_id")),
        actor_id=str(raw.get("actor_id") or "").strip() or None,
        target_ids=target_ids,
        content=str(raw.get("content") or ""),
        payload=payload,
        visibility=visibility or {"player_visible": True, "gm_visible": True},
        created_at=str(raw.get("created_at") or "") or utcnow().isoformat(),
    )


def _iter_action_board_cards(session: GameSession):
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    board = mem.get(_ACTION_BOARD_KEY)
    if not isinstance(board, dict):
        return
    scenes = board.get("scenes")
    if not isinstance(scenes, dict):
        return
    for scene_id, cards in scenes.items():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if isinstance(card, dict) and card.get("card_id"):
                yield str(scene_id), card


def _iter_action_board_cards_from_board(board: ActionBoard):
    raw = board.to_dict()
    scenes = raw.get("scenes") if isinstance(raw, dict) else None
    if not isinstance(scenes, dict):
        return
    for scene_id, cards in scenes.items():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if isinstance(card, dict) and card.get("card_id"):
                yield str(scene_id), card
