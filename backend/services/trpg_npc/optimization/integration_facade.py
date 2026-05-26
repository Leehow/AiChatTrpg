"""Optional facade showing how the hardening helpers fit into pre-turn runtime.

This is not meant to replace your existing ``runtime_adapter``.  It is a small
reference implementation you can borrow from when patching
``build_npc_pre_turn_runtime`` and ``warm_npc_action_board_after_turn``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .action_board_guard import ActionCardMatch, filter_action_cards_for_turn
from .common import get_value
from .event_classifier import classify_player_text_to_events
from .safe_projection import prompt_safe_active_npcs_hardened
from .scene_beat_plan_guard import render_npc_beat_plan_section


@dataclass(slots=True)
class HardenedPreTurnFrame:
    safe_active_npcs: list[dict[str, Any]]
    classified_events: list[dict[str, Any]]
    action_card_matches: list[dict[str, Any]]
    npc_beat_plan_section: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe_active_npcs": self.safe_active_npcs,
            "classified_events": self.classified_events,
            "action_card_matches": self.action_card_matches,
            "npc_beat_plan_section": self.npc_beat_plan_section,
            "warnings": self.warnings,
        }


def build_hardened_pre_turn_frame(
    *,
    session: Any,
    player_text: str,
    active_npcs: list[Any],
    turn_id: int,
    scene_id: str,
    action_cards: list[Any] | None = None,
    max_action_cards: int = 4,
) -> HardenedPreTurnFrame:
    safe_active_npcs = prompt_safe_active_npcs_hardened(active_npcs)
    classified_events = classify_player_text_to_events(
        player_text,
        active_npcs,
        scene_id=scene_id,
        turn_id=turn_id,
    )
    matches: list[ActionCardMatch] = filter_action_cards_for_turn(
        action_cards or [],
        events=classified_events,
        player_text=player_text,
        current_turn=turn_id,
        current_scene_id=scene_id,
        max_cards=max_action_cards,
    )

    beat_plan = {
        "turn_id": turn_id,
        "scene_id": scene_id,
        "classified_player_events": classified_events,
        "matched_action_cards": [m.to_dict() for m in matches],
        "constraints": [
            "NPC action cards are intent proposals, not canon events.",
            "Only narrate resolved/allowed beats from ActionResolver.",
            "Do not reveal forbidden facts or private NPC metadata.",
        ],
    }
    return HardenedPreTurnFrame(
        safe_active_npcs=safe_active_npcs,
        classified_events=classified_events,
        action_card_matches=[m.to_dict() for m in matches],
        npc_beat_plan_section=render_npc_beat_plan_section(beat_plan),
    )
