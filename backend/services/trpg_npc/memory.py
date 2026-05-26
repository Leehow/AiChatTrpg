"""Event-driven memory writer."""
from __future__ import annotations

from .models import GameEvent, MemoryRecord
from .utils import new_id


class MemoryWriter:
    """Write concise event memories instead of raw chat transcripts."""

    IMPORTANT_TYPES = {
        "PLAYER_INPUT",
        "HELPED_NPC",
        "PROTECTED_NPC",
        "THREATENED_NPC",
        "ASKED_SENSITIVE_QUESTION",
        "REVEALED_EVIDENCE",
        "BROKE_PROMISE",
        "PUBLIC_EXPOSURE",
        "NPC_REVEALED_CLUE",
        "CLUE_REVEALED",
        "PHYSICAL_ATTACK",
    }

    def write_from_event(self, npc_id: str, event: GameEvent, importance: float | None = None) -> MemoryRecord | None:
        if event.type not in self.IMPORTANT_TYPES and npc_id not in event.target_ids:
            return None
        imp = importance if importance is not None else self._importance(event)
        content = self._summarize(npc_id, event)
        return MemoryRecord(
            memory_id=new_id("mem"),
            npc_id=npc_id,
            memory_type="episodic",
            content=content,
            importance=imp,
            source_event_ids=[event.event_id],
            tags=[event.type.lower()],
        )

    def _importance(self, event: GameEvent) -> float:
        if event.type in {"PHYSICAL_ATTACK", "BROKE_PROMISE", "CLUE_REVEALED", "PUBLIC_EXPOSURE"}:
            return 0.90
        if event.type in {"THREATENED_NPC", "ASKED_SENSITIVE_QUESTION", "REVEALED_EVIDENCE"}:
            return 0.75
        return 0.55

    def _summarize(self, npc_id: str, event: GameEvent) -> str:
        actor = event.actor_id or "unknown actor"
        target_note = "directly affected this NPC" if npc_id in event.target_ids else "was visible/heard by this NPC"
        return f"Turn {event.turn_id}: {actor} caused event {event.type}; {target_note}. Content: {event.content[:180]}"
