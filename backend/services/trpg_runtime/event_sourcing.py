"""Semantic event-sourcing helpers for ChatRPG turns.

This module turns GM-emitted ``GameEvent`` objects into canonical
``StateChange`` rows without asking another LLM to infer meaning from prose.
Structured events keep their visibility metadata all the way through the
runtime so hidden clues can be stored for the GM without leaking to players.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from services.trpg_context.models import Visibility
from services.trpg_memory.memory_models import MemoryKind, TruthStatus
from services.trpg_npc.models import GameEvent
from services.trpg_runtime.turn_output_contract import (
    StateChange,
    StateChangeType,
    StateOperation,
)

_DISCOVERY_TYPES = {
    "discovery",
    "discover",
    "clue",
    "clue_discovered",
    "player_discovery",
    "reveal",
    "finding",
}
_LOCATION_TYPES = {
    "entity_location",
    "item_location",
    "location_change",
    "move_entity",
    "item_moved",
    "object_location",
}
_SCENE_TYPES = {
    "scene_transition",
    "change_scene",
    "enter_scene",
    "location_entered",
}
_RELATIONSHIP_TYPES = {
    "npc_attitude",
    "relationship",
    "relationship_update",
    "npc_relationship",
}
_EMOTION_TYPES = {
    "npc_emotion",
    "emotion",
    "mood",
}
_PLOT_TYPES = {
    "plot",
    "plot_flag",
    "objective",
    "thread",
    "quest",
}


@dataclass(frozen=True)
class SemanticEventView:
    event: GameEvent
    normalized_type: str
    visibility: Visibility
    player_visible: bool
    content: str
    payload: dict[str, Any]

    @property
    def is_discovery(self) -> bool:
        return self.normalized_type in _DISCOVERY_TYPES

    @property
    def is_plot(self) -> bool:
        return self.normalized_type in _PLOT_TYPES

    @property
    def memory_kind(self) -> MemoryKind:
        if self.normalized_type in _DISCOVERY_TYPES:
            return MemoryKind.CLUE
        if self.normalized_type in _RELATIONSHIP_TYPES:
            return MemoryKind.RELATIONSHIP
        if self.normalized_type in _EMOTION_TYPES:
            return MemoryKind.EMOTION
        if self.normalized_type in _PLOT_TYPES:
            return MemoryKind.PLOT
        return MemoryKind.PLOT

    @property
    def truth_status(self) -> TruthStatus:
        if self.visibility == Visibility.GM_ONLY:
            return TruthStatus.GM_SECRET
        if self.memory_kind in {MemoryKind.RELATIONSHIP, MemoryKind.EMOTION}:
            return TruthStatus.BELIEF
        return TruthStatus.TRUE


def normalize_event_type(value: str | None) -> str:
    raw = str(value or "").strip().casefold()
    raw = raw.replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "", raw) or "gm_structured_event"


def is_player_visible_event(event: GameEvent) -> bool:
    raw = getattr(event, "visibility", None)
    if not isinstance(raw, dict):
        return True
    return bool(raw.get("player_visible", True))


def event_visibility(event: GameEvent) -> Visibility:
    raw = getattr(event, "visibility", None)
    if isinstance(raw, dict):
        if raw.get("gm_only") is True or raw.get("player_visible") is False:
            return Visibility.GM_ONLY
        if raw.get("npc_private"):
            return Visibility.NPC_PRIVATE
        if raw.get("public") is True:
            return Visibility.PUBLIC
    return Visibility.PARTY_KNOWN


def semantic_event_view(event: GameEvent) -> SemanticEventView:
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        payload = {}
    return SemanticEventView(
        event=event,
        normalized_type=normalize_event_type(getattr(event, "type", "")),
        visibility=event_visibility(event),
        player_visible=is_player_visible_event(event),
        content=str(getattr(event, "content", "") or "").strip(),
        payload=dict(payload),
    )


def iter_semantic_events(events: Iterable[GameEvent]) -> tuple[SemanticEventView, ...]:
    return tuple(semantic_event_view(event) for event in events)


def is_discovery_event_type(value: str | None) -> bool:
    return normalize_event_type(value) in _DISCOVERY_TYPES


def event_memory_subjects(view: SemanticEventView) -> tuple[str, ...]:
    payload = view.payload
    subjects: list[str] = []
    for key in ("subject_id", "entity_id", "item_id", "npc_id", "clue_id", "plot_id"):
        value = payload.get(key)
        if value:
            subjects.append(str(value))
    for value in getattr(view.event, "target_ids", None) or []:
        if value:
            subjects.append(str(value))
    if not subjects:
        if view.memory_kind == MemoryKind.CLUE:
            subjects.append(_stable_slug(payload.get("clue_id") or view.content or view.event.event_id, prefix="clue"))
        elif view.memory_kind == MemoryKind.PLOT:
            subjects.append(_stable_slug(payload.get("plot_id") or view.content or view.event.event_id, prefix="plot"))
        else:
            subjects.append("party")
    return tuple(_dedupe(subjects))


def event_owner_id(view: SemanticEventView) -> str | None:
    if view.visibility != Visibility.NPC_PRIVATE:
        return None
    payload_owner = view.payload.get("owner_id") or view.payload.get("npc_id")
    if payload_owner:
        return str(payload_owner)
    actor_id = getattr(view.event, "actor_id", None)
    return str(actor_id) if actor_id else None


def semantic_state_changes_for_event(view: SemanticEventView, *, turn_id: str) -> tuple[StateChange, ...]:
    event = view.event
    payload = view.payload
    base_tags = ("structured_event", view.normalized_type, "semantic")
    source_turn = turn_id

    if view.normalized_type in _DISCOVERY_TYPES:
        clue_id = str(payload.get("clue_id") or payload.get("id") or _stable_slug(view.content or event.event_id, prefix="clue"))
        return (StateChange(
            change_id=_change_id(turn_id, "clue", event.event_id),
            type=StateChangeType.CLUE_DISCOVERED,
            target_id=clue_id,
            operation=StateOperation.MERGE,
            value={
                "clue_id": clue_id,
                "status": "discovered" if view.player_visible else "hidden",
                "summary": view.content[:500],
                "source_event_id": event.event_id,
                "source_turn_id": source_turn,
                "player_visible": view.player_visible,
                "visibility": view.visibility.value,
                "points_to": _as_str_list(payload.get("points_to")),
                "raw_type": getattr(event, "type", ""),
            },
            path=("clues", clue_id),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=1.0,
            reason=view.content[:300],
            tags=base_tags + ("clue_ledger",),
            metadata={"source_event_id": event.event_id},
        ),)

    if view.normalized_type in _LOCATION_TYPES:
        target_id = str(
            payload.get("entity_id")
            or payload.get("item_id")
            or (event.target_ids[0] if getattr(event, "target_ids", None) else "")
            or _stable_slug(view.content or event.event_id, prefix="entity")
        )
        location = payload.get("location") or payload.get("to") or payload.get("new_location") or view.content
        return (StateChange(
            change_id=_change_id(turn_id, "entity_location", event.event_id),
            type=StateChangeType.ENTITY_LOCATION,
            target_id=target_id,
            operation=StateOperation.MERGE,
            value={
                "location": str(location or ""),
                "last_seen_turn": source_turn,
                "source_event_id": event.event_id,
                "visibility": view.visibility.value,
            },
            path=("entities", target_id),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=1.0,
            reason=view.content[:300],
            tags=base_tags + ("entity_graph",),
            metadata={"source_event_id": event.event_id},
        ),)

    if view.normalized_type in _SCENE_TYPES:
        scene_id = str(payload.get("scene_id") or payload.get("to_scene") or getattr(event, "scene_id", "") or "scene_unknown")
        return (StateChange(
            change_id=_change_id(turn_id, "scene", event.event_id),
            type=StateChangeType.SCENE_TRANSITION,
            target_id=scene_id,
            operation=StateOperation.SET,
            value={
                "scene_id": scene_id,
                "summary": view.content[:500],
                "source_event_id": event.event_id,
                "visibility": view.visibility.value,
            },
            path=("scene", "current"),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=1.0,
            reason=view.content[:300],
            tags=base_tags + ("scene",),
            metadata={"source_event_id": event.event_id},
        ),)

    if view.normalized_type in _RELATIONSHIP_TYPES:
        npc_id = str(payload.get("npc_id") or getattr(event, "actor_id", "") or (event.target_ids[0] if getattr(event, "target_ids", None) else "") or "npc_unknown")
        subject_id = str(payload.get("subject_id") or payload.get("toward") or "party")
        return (StateChange(
            change_id=_change_id(turn_id, "npc_attitude", event.event_id),
            type=StateChangeType.NPC_ATTITUDE,
            target_id=npc_id,
            operation=StateOperation.MERGE,
            value={
                "summary": view.content[:500],
                "attitude": payload.get("attitude") or payload.get("value"),
                "delta": payload.get("delta"),
                "source_event_id": event.event_id,
                "visibility": view.visibility.value,
            },
            path=("npcs", npc_id, "relationships", subject_id),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=0.9,
            reason=view.content[:300],
            tags=base_tags + ("relationship",),
            metadata={"source_event_id": event.event_id},
        ),)

    if view.normalized_type in _EMOTION_TYPES:
        npc_id = str(payload.get("npc_id") or getattr(event, "actor_id", "") or (event.target_ids[0] if getattr(event, "target_ids", None) else "") or "npc_unknown")
        return (StateChange(
            change_id=_change_id(turn_id, "npc_emotion", event.event_id),
            type=StateChangeType.NPC_EMOTION,
            target_id=npc_id,
            operation=StateOperation.MERGE,
            value={
                "summary": view.content[:500],
                "emotion": payload.get("emotion") or payload.get("mood") or payload.get("value"),
                "source_event_id": event.event_id,
                "visibility": view.visibility.value,
            },
            path=("npcs", npc_id, "emotion"),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=0.85,
            reason=view.content[:300],
            tags=base_tags + ("emotion",),
            metadata={"source_event_id": event.event_id},
        ),)

    if view.normalized_type in _PLOT_TYPES:
        plot_id = str(payload.get("plot_id") or payload.get("title") or _stable_slug(view.content or event.event_id, prefix="plot"))
        return (StateChange(
            change_id=_change_id(turn_id, "plot", event.event_id),
            type=StateChangeType.CUSTOM,
            target_id=plot_id,
            operation=StateOperation.MERGE,
            value={
                "summary": view.content[:500],
                "status": payload.get("status") or "active",
                "source_event_id": event.event_id,
                "visibility": view.visibility.value,
            },
            path=("plot", "threads", plot_id),
            actor_id=getattr(event, "actor_id", None),
            source_turn_id=source_turn,
            visibility=view.visibility,
            confidence=0.9,
            reason=view.content[:300],
            tags=base_tags + ("plot_thread",),
            metadata={"source_event_id": event.event_id},
        ),)

    return ()


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if value is None:
        return []
    return [str(value)] if str(value).strip() else []


def _stable_slug(value: Any, *, prefix: str) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return f"{prefix}_unknown"
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    if not normalized:
        normalized = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{normalized[:48]}"


def _change_id(*parts: str) -> str:
    clean = [str(p).strip().replace(" ", "_") for p in parts if str(p).strip()]
    return "chg_" + "_".join(clean)[:88]
