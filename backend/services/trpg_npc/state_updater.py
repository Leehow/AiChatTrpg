"""State vector update logic.

This module should stay deterministic and cheap. The LLM may help classify
complex events, but committed mood/relationship updates should be traceable.
"""
from __future__ import annotations

from copy import deepcopy

from .models import EventAppraisal, MoodVector, NPCProfile, NPCState, RelationshipVector
from .utils import clamp, clamp_signed, now_iso, weighted_average


class StateVectorUpdater:
    """Apply EventAppraisal to NPCState and relationship vectors."""

    def apply(
        self,
        profile: NPCProfile,
        state: NPCState,
        appraisal: EventAppraisal,
        actor_id: str | None = None,
        relationships: dict[str, RelationshipVector] | None = None,
        commit: bool = True,
    ) -> tuple[NPCState, dict[str, RelationshipVector]]:
        relationships = relationships or {}
        next_state = state if commit else deepcopy(state)
        next_relationships = relationships if commit else deepcopy(relationships)

        self._apply_mood(profile, next_state, appraisal)
        if actor_id:
            rel = next_relationships.get(actor_id, RelationshipVector())
            next_relationships[actor_id] = self._apply_relationship(rel, appraisal, profile)
        self._apply_goal_pressure(next_state, appraisal)
        next_state.state_version += 1
        next_state.updated_at = now_iso()
        return next_state, next_relationships

    def preview_delta(
        self,
        profile: NPCProfile,
        state: NPCState,
        appraisal: EventAppraisal,
        actor_id: str | None = None,
        relationship: RelationshipVector | None = None,
    ) -> tuple[dict[str, float], dict[str, RelationshipVector], dict[str, float]]:
        before = deepcopy(state)
        rels = {actor_id: deepcopy(relationship or RelationshipVector())} if actor_id else {}
        before_relationships = deepcopy(rels)
        after, after_rels = self.apply(profile, deepcopy(state), appraisal, actor_id=actor_id, relationships=rels, commit=True)
        mood_delta = {}
        for k, v in after.mood.as_float_dict().items():
            old_v = before.mood.as_float_dict()[k]
            mood_delta[k] = round(float(v) - float(old_v), 4)
        rel_delta: dict[str, RelationshipVector] = {}
        if actor_id:
            before_rel = before_relationships[actor_id]
            after_rel = after_rels[actor_id]
            rel_delta[actor_id] = RelationshipVector(
                trust=after_rel.trust - before_rel.trust,
                respect=after_rel.respect - before_rel.respect,
                fear=after_rel.fear - before_rel.fear,
                suspicion=after_rel.suspicion - before_rel.suspicion,
                resentment=after_rel.resentment - before_rel.resentment,
                debt=after_rel.debt - before_rel.debt,
                affinity=after_rel.affinity - before_rel.affinity,
            )
        goal_delta = {
            "protect_secret": round(appraisal.secret_exposure * 0.30, 4),
            "avoid_public_attention": round(appraisal.public_pressure * 0.25 + appraisal.social_exposure * 0.20, 4),
            "survive": round(appraisal.physical_threat * 0.35 + appraisal.threat * 0.20, 4),
        }
        return mood_delta, rel_delta, goal_delta

    def _apply_mood(self, profile: NPCProfile, state: NPCState, a: EventAppraisal) -> None:
        p = profile.persona.normalized()
        m = state.mood
        b = profile.baseline_mood.normalized()

        # Recovery toward baseline. High neuroticism/fanaticism creates stronger inertia.
        recovery = clamp(0.16 - p.neuroticism * 0.07 - p.fanaticism * 0.04, 0.04, 0.20)
        m.valence = weighted_average(m.valence, b.valence, recovery)
        m.arousal = weighted_average(m.arousal, b.arousal, recovery)
        m.dominance_feeling = weighted_average(m.dominance_feeling, b.dominance_feeling, recovery)
        for name in ["fear", "anger", "sadness", "joy", "disgust", "shame", "curiosity", "suspicion", "stress", "fatigue"]:
            setattr(m, name, weighted_average(getattr(m, name), getattr(b, name), recovery))

        m.fear += a.threat * (0.18 + p.neuroticism * 0.25 + p.paranoia * 0.20) + a.physical_threat * 0.35
        m.anger += a.insult * (0.15 + p.dominance * 0.20 + (1.0 - p.impulse_control) * 0.10) + a.betrayal * 0.22
        m.suspicion += a.uncertainty * (0.20 + p.paranoia * 0.35) + a.secret_exposure * (0.25 + p.paranoia * 0.20)
        m.curiosity += a.evidence * (0.18 + p.openness * 0.20) + a.uncertainty * p.openness * 0.12
        m.stress += a.threat * 0.20 + a.secret_exposure * 0.35 + a.goal_block * 0.22 + a.public_pressure * 0.18
        m.shame += a.social_exposure * (0.08 + p.agreeableness * 0.10)
        m.joy += a.help * (0.12 + p.empathy * 0.12) + a.protected * 0.10
        m.disgust += a.insult * 0.08 + a.betrayal * 0.10

        m.valence += a.help * 0.20 + a.protected * 0.10 + a.offer * 0.08
        m.valence -= a.threat * 0.18 + a.insult * 0.12 + a.betrayal * 0.20 + a.secret_exposure * 0.10
        m.arousal += a.threat * 0.20 + a.physical_threat * 0.20 + a.secret_exposure * 0.18 + a.evidence * 0.05
        m.dominance_feeling += p.dominance * 0.03 - a.threat * 0.08 - a.secret_exposure * 0.05 + a.offer * 0.04
        m.normalized()

    def _apply_relationship(self, rel: RelationshipVector, a: EventAppraisal, profile: NPCProfile) -> RelationshipVector:
        p = profile.persona.normalized()
        rel.trust += a.help * (0.18 + p.empathy * 0.08) + a.protected * 0.22 + a.offer * 0.05
        rel.trust -= a.threat * 0.18 + a.betrayal * 0.30 + a.secret_exposure * 0.08
        rel.respect += a.evidence * 0.10 + a.offer * 0.04 + a.protected * 0.06
        rel.fear += a.threat * 0.20 + a.physical_threat * 0.35
        rel.suspicion += a.uncertainty * 0.18 + a.secret_exposure * 0.22 + a.betrayal * 0.25
        rel.resentment += a.insult * 0.22 + a.threat * 0.10 + a.betrayal * 0.20
        rel.debt += a.help * 0.12 + a.protected * 0.22 - a.betrayal * 0.10
        rel.affinity += a.help * 0.06 - a.insult * 0.08 - a.threat * 0.05
        return rel.normalized()

    def _apply_goal_pressure(self, state: NPCState, a: EventAppraisal) -> None:
        state.goal_pressure["protect_secret"] = clamp(state.goal_pressure.get("protect_secret", 0.0) + a.secret_exposure * 0.30)
        state.goal_pressure["avoid_public_attention"] = clamp(
            state.goal_pressure.get("avoid_public_attention", 0.0) + a.public_pressure * 0.25 + a.social_exposure * 0.20
        )
        state.goal_pressure["survive"] = clamp(
            state.goal_pressure.get("survive", 0.0) + a.physical_threat * 0.35 + a.threat * 0.20
        )
        # Signed values are not used here, but clamp defensively.
        for k in list(state.goal_pressure.keys()):
            state.goal_pressure[k] = clamp(state.goal_pressure[k])
