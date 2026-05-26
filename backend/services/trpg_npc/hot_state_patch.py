"""Foreground temporary state patches.

Hot patches are not committed. They let the current turn feel responsive even
when the full post-turn worker has not finished updating persistent NPC state.
"""
from __future__ import annotations

from .appraiser import EventAppraiser
from .behavior_policy import BehaviorPolicyCompiler
from .models import GameEvent, HotStatePatch, NPCProfile, NPCState, RelationshipVector
from .state_updater import StateVectorUpdater


class HotStatePatchEngine:
    def __init__(self, appraiser: EventAppraiser | None = None, updater: StateVectorUpdater | None = None):
        self.appraiser = appraiser or EventAppraiser()
        self.updater = updater or StateVectorUpdater()
        self.policy_compiler = BehaviorPolicyCompiler()

    def patch_for_event(
        self,
        event: GameEvent,
        profile: NPCProfile,
        state: NPCState,
        actor_relationship: RelationshipVector | None = None,
        scene_tags: list[str] | None = None,
    ) -> HotStatePatch:
        appraisal = self.appraiser.appraise(
            event,
            npc_profile=profile,
            npc_state=state,
            relationship=actor_relationship,
            scene_tags=scene_tags,
        )
        mood_delta, rel_delta, goal_delta = self.updater.preview_delta(
            profile,
            state,
            appraisal,
            actor_id=event.actor_id,
            relationship=actor_relationship,
        )
        # Compile policy against a copied preview state for current turn rendering.
        preview_state, preview_rels = self.updater.apply(
            profile,
            state,
            appraisal,
            actor_id=event.actor_id,
            relationships={event.actor_id: actor_relationship or RelationshipVector()} if event.actor_id else {},
            commit=False,
        )
        temporary_policy = self.policy_compiler.compile(profile, preview_state, preview_rels, target_id=event.actor_id)
        return HotStatePatch(
            npc_id=profile.npc_id,
            patch_reason=f"{event.type}: {event.content[:120]}",
            temporary_mood_delta=mood_delta,
            temporary_relationship_delta=rel_delta,
            temporary_goal_pressure_delta=goal_delta,
            temporary_policy=temporary_policy,
        )
