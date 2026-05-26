"""Simple faction clock planner for off-screen pressure."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import GameEvent
from .utils import clamp, new_id


@dataclass(slots=True)
class FactionClock:
    clock_id: str
    label: str
    current: int = 0
    max_value: int = 6

    def tick(self, amount: int = 1) -> None:
        self.current = min(self.max_value, self.current + amount)

    @property
    def complete(self) -> bool:
        return self.current >= self.max_value


@dataclass(slots=True)
class FactionState:
    faction_id: str
    name: str
    agenda: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    clocks: dict[str, FactionClock] = field(default_factory=dict)


class FactionPlanner:
    """Move background organizations with clocks instead of per-NPC LLM calls."""

    def react_to_event(self, faction: FactionState, event: GameEvent) -> list[GameEvent]:
        created: list[GameEvent] = []
        text = event.content.lower()
        if any(word in text for word in ["邪教", "cult", "ritual", "秘密", "secret"]):
            self._tick(faction, "suspicion_of_players", "Suspicion of players", 1)
        if event.type in {"PHYSICAL_ATTACK", "PUBLIC_EXPOSURE", "CLUE_REVEALED"}:
            self._tick(faction, "retaliation", "Retaliation pressure", 1)
        for clock in faction.clocks.values():
            if clock.complete:
                created.append(GameEvent(
                    event_id=new_id("event"),
                    type="FACTION_CLOCK_COMPLETED",
                    scene_id=event.scene_id,
                    turn_id=event.turn_id,
                    actor_id=faction.faction_id,
                    content=f"Faction clock completed: {clock.label}",
                    payload={"clock_id": clock.clock_id, "clock": clock.label, "value": clock.current},
                    visibility={"player_visible": False, "gm_visible": True},
                ))
        return created

    def _tick(self, faction: FactionState, clock_id: str, label: str, amount: int) -> None:
        if clock_id not in faction.clocks:
            faction.clocks[clock_id] = FactionClock(clock_id=clock_id, label=label)
        faction.clocks[clock_id].tick(amount)
