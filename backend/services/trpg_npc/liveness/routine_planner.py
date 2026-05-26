"""Post-output routine/offscreen liveness planner.

This module is safe to run after the visible reply. It should not block the
user-facing turn. It emits compact suggestions/events that can be persisted or
fed into the existing background planner.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .common import get_value, short_text


@dataclass(slots=True)
class OffscreenRoutineEvent:
    npc_id: str
    scene_id: str
    event_type: str
    summary: str
    priority: float = 0.3
    player_visible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RoutinePlanner:
    def plan_after_visible_reply(
        self,
        *,
        active_npcs: list[Any],
        scene_id: str,
        in_game_period: str = "",
        max_events: int = 3,
    ) -> list[OffscreenRoutineEvent]:
        events: list[OffscreenRoutineEvent] = []
        period = (in_game_period or "").lower()
        for npc in active_npcs or []:
            npc_id = str(get_value(npc, "key") or get_value(npc, "npc_id") or "")
            if not npc_id:
                continue
            card = get_value(npc, "liveness_card_v2") or {}
            routine = ""
            if isinstance(card, dict):
                routine = str(card.get("daily_routine_hint") or "")
            if not routine:
                continue
            if period and not _period_relevant(period, routine):
                continue
            events.append(OffscreenRoutineEvent(
                npc_id=npc_id,
                scene_id=scene_id,
                event_type="NPC_ROUTINE_TICK",
                summary=short_text(routine, max_len=240),
                priority=0.35,
                player_visible=False,
            ))
            if len(events) >= max_events:
                break
        return events


def _period_relevant(period: str, routine: str) -> bool:
    if not period:
        return True
    text = routine.lower()
    return any(token in text for token in [period, "打烊", "夜", "morning", "evening", "night"]) or True
