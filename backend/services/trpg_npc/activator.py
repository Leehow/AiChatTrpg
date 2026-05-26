"""Select which NPCs deserve foreground synchronous processing."""
from __future__ import annotations

from .action_board import ActionBoardMatch
from .models import GameEvent, NPCProfile, NPCTier, SceneState


class NPCActivator:
    """Hot / warm / cold routing for NPCs."""

    HOT_TIERS = {NPCTier.SUPPORTING, NPCTier.MAJOR}

    def select_hot_npcs(
        self,
        scene_state: SceneState,
        event: GameEvent,
        profiles_by_id: dict[str, NPCProfile],
        matched_cards: list[ActionBoardMatch],
        max_count: int = 1,
    ) -> list[str]:
        candidates: dict[str, float] = {}

        for npc_id in event.target_ids:
            if npc_id in scene_state.active_npc_ids:
                candidates[npc_id] = candidates.get(npc_id, 0.0) + 2.0

        for match in matched_cards:
            candidates[match.card.npc_id] = candidates.get(match.card.npc_id, 0.0) + match.score

        for npc_id, profile in profiles_by_id.items():
            if npc_id not in scene_state.active_npc_ids:
                continue
            if profile.tier in self.HOT_TIERS and profile.narrative_role in {"clue_holder", "antagonist", "ally", "gatekeeper"}:
                candidates[npc_id] = candidates.get(npc_id, 0.0) + 0.35

        scored = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        return [npc_id for npc_id, _ in scored[:max_count]]

    def classify_npc(self, npc_id: str, scene_state: SceneState, event: GameEvent, profile: NPCProfile) -> str:
        if npc_id in event.target_ids:
            return "hot"
        if npc_id in scene_state.active_npc_ids and profile.tier in self.HOT_TIERS:
            return "warm"
        return "cold"
