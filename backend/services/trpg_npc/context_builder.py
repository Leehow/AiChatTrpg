"""Build NPCPerceptionPacket from canonical scene state.

This module is where your existing visibility.py should plug in. The key is
that NPC agents only see this packet, never the full campaign truth.
"""
from __future__ import annotations

from .models import Fact, GameEvent, NPCPerceptionPacket, NPCProfile, RelationshipVector, SceneState


class NPCContextBuilder:
    def build(
        self,
        npc_id: str,
        scene_state: SceneState,
        recent_events: list[GameEvent],
        profile: NPCProfile,
        relationships: dict[str, RelationshipVector] | None = None,
        relevant_memories: list[dict] | None = None,
    ) -> NPCPerceptionPacket:
        known_facts = self._filter_known_facts(npc_id, scene_state.facts_by_id, profile)
        forbidden = list(dict.fromkeys(
            profile.plot_constraints.forbidden_fact_ids
            + profile.plot_constraints.core_secret_ids
            + (scene_state.plot_contract.forbidden_reveals if scene_state.plot_contract else [])
        ))
        visible_events = self._filter_visible_events(npc_id, recent_events)
        return NPCPerceptionPacket(
            npc_id=npc_id,
            scene_id=scene_state.scene_id,
            turn_id=scene_state.turn_id,
            visible_events=visible_events,
            heard_dialogues=[e for e in visible_events if "DIALOGUE" in e.type or e.type == "PLAYER_INPUT"],
            visible_entities=[{"entity_id": x, "kind": "npc", "active": True} for x in scene_state.active_npc_ids],
            known_facts=known_facts,
            relevant_memories=relevant_memories or [],
            relationship_snapshot=relationships or {},
            rule_constraints={"action_budget": scene_state.action_budget},
            forbidden_fact_ids=forbidden,
        )

    def _filter_known_facts(self, npc_id: str, facts: dict[str, Fact], profile: NPCProfile) -> list[Fact]:
        allowed = set(profile.knowledge_fact_ids)
        out: list[Fact] = []
        for fact_id, fact in facts.items():
            if fact.gm_only and npc_id not in fact.known_by:
                continue
            if npc_id in fact.known_by or fact_id in allowed:
                out.append(fact)
        return out

    def _filter_visible_events(self, npc_id: str, events: list[GameEvent]) -> list[GameEvent]:
        # Replace this method with your existing line-of-sight / hearing logic.
        out = []
        for event in events:
            if event.visibility.get("gm_visible") is False:
                continue
            if event.visibility.get("player_visible", True):
                out.append(event)
                continue
            if npc_id in event.target_ids or npc_id == event.actor_id:
                out.append(event)
        return out
