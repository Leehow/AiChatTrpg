"""Progressive NPC data generation and promotion helpers.

You do NOT need to generate a huge full profile for every NPC. Generate by tier:
- L0: name/role/location/one-line voice only.
- L1: add simple motive, baseline mood, basic relationship defaults.
- L2: add plot constraints, known facts, modes, action planning.
- L3: add full persona, secrets, memory, modes, faction hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    MoodVector,
    NPCMode,
    NPCProfile,
    NPCState,
    NPCTier,
    PersonaVector,
    PlotConstraints,
    VoiceCard,
)
from .utils import new_id


@dataclass(slots=True)
class NPCGenerationSpec:
    name: str
    narrative_role: str = "ambient"
    tier: NPCTier = NPCTier.MINOR
    campaign_id: str | None = None
    chapter_id: str | None = None
    scene_id: str | None = None
    location_id: str | None = None
    occupation: str = ""
    first_impression: str = ""
    public_appearance: str = ""
    true_goal: str = ""
    fear: str = ""
    tone: str = "neutral"
    tags: list[str] = field(default_factory=list)
    knowledge_fact_ids: list[str] = field(default_factory=list)
    secret_ids: list[str] = field(default_factory=list)


class NPCFactory:
    def create(self, spec: NPCGenerationSpec) -> tuple[NPCProfile, NPCState]:
        npc_id = new_id("npc")
        profile = NPCProfile(
            npc_id=npc_id,
            name=spec.name,
            tier=spec.tier,
            narrative_role=spec.narrative_role,
            anchor={
                k: v for k, v in {
                    "campaign_id": spec.campaign_id,
                    "chapter_id": spec.chapter_id,
                    "scene_id": spec.scene_id,
                    "location_id": spec.location_id,
                }.items() if v
            },
            public_card={
                "appearance": spec.public_appearance,
                "occupation": spec.occupation,
                "first_impression": spec.first_impression,
            },
            private_card={
                "true_goal": spec.true_goal,
                "fear": spec.fear,
            },
            persona=self._persona_for_tier(spec),
            baseline_mood=self._baseline_for_role(spec),
            voice_card=VoiceCard(tone=spec.tone, register="plain", sentence_length="medium"),
            modes=self._modes_for_tier(spec),
            plot_constraints=self._constraints_for_role(spec),
            knowledge_fact_ids=list(spec.knowledge_fact_ids),
            secret_ids=list(spec.secret_ids),
            tags=list(spec.tags),
        )
        state = NPCState(
            npc_id=npc_id,
            scene_id=spec.scene_id,
            location_id=spec.location_id,
            current_mode=profile.default_mode_id(),
            mood=profile.baseline_mood,
        )
        return profile, state

    def promote(self, profile: NPCProfile, to_tier: NPCTier, reason: str = "") -> NPCProfile:
        """Fill missing structures when an NPC becomes important."""
        profile.tier = to_tier
        profile.tags = list(dict.fromkeys(profile.tags + ["promoted", reason] if reason else profile.tags + ["promoted"]))
        if to_tier in {NPCTier.SUPPORTING, NPCTier.MAJOR} and not profile.modes:
            profile.modes = [
                NPCMode("default", "Default", visible_expression="neutral"),
                NPCMode("guarded", "Guarded", visible_expression="polite_but_guarded", policy_bias={"deception_level": 0.15}),
            ]
        if to_tier == NPCTier.MAJOR:
            profile.plot_constraints.must_preserve_clue_path = True
            profile.plot_constraints.max_clue_reveals_per_turn = 1
            profile.persona.deception_skill = max(profile.persona.deception_skill, 0.45)
        return profile

    def _persona_for_tier(self, spec: NPCGenerationSpec) -> PersonaVector:
        p = PersonaVector()
        if spec.narrative_role in {"antagonist", "cultist", "spy"}:
            p.paranoia = 0.60
            p.deception_skill = 0.65
            p.agreeableness = 0.25
            p.ambition = 0.70
        if spec.narrative_role in {"clue_holder", "witness"}:
            p.neuroticism = 0.60
            p.paranoia = 0.45
            p.empathy = 0.55
        if spec.tier == NPCTier.MAJOR:
            p.conscientiousness = 0.70
            p.impulse_control = 0.65
        return p.normalized()

    def _baseline_for_role(self, spec: NPCGenerationSpec) -> MoodVector:
        mood = MoodVector()
        if spec.narrative_role in {"witness", "clue_holder"}:
            mood.fear = 0.20
            mood.suspicion = 0.35
            mood.stress = 0.30
        if spec.narrative_role in {"antagonist", "cultist", "spy"}:
            mood.suspicion = 0.45
            mood.dominance_feeling = 0.60
            mood.stress = 0.25
        return mood.normalized()

    def _modes_for_tier(self, spec: NPCGenerationSpec) -> list[NPCMode]:
        if spec.tier in {NPCTier.BACKGROUND, NPCTier.MINOR}:
            return [NPCMode("default", "Default", visible_expression="neutral")]
        if spec.narrative_role in {"antagonist", "cultist", "spy"}:
            return [
                NPCMode("public_face", "Public Face", "Social mask", "polite_but_guarded", policy_bias={"deception_level": 0.10}),
                NPCMode("cornered", "Cornered", "When exposed or threatened", "coldly_hostile", policy_bias={"aggression_level": 0.20, "risk_tolerance": -0.10}),
            ]
        return [
            NPCMode("default", "Default", visible_expression="neutral"),
            NPCMode("trusting", "Trusting", visible_expression="open_but_cautious", policy_bias={"cooperation_level": 0.20}),
            NPCMode("guarded", "Guarded", visible_expression="polite_but_guarded", policy_bias={"deception_level": 0.15}),
        ]

    def _constraints_for_role(self, spec: NPCGenerationSpec) -> PlotConstraints:
        constraints = PlotConstraints()
        constraints.forbidden_fact_ids = list(spec.secret_ids)
        constraints.core_secret_ids = list(spec.secret_ids)
        if spec.narrative_role in {"clue_holder", "witness"}:
            constraints.minimum_clue_output = "one_minor_lead_if_players_succeed"
            constraints.can_attack_players = "never"
        if spec.narrative_role in {"antagonist", "cultist"}:
            constraints.can_attack_players = "only_if_exposed_or_cornered"
            constraints.allowed_escalations = ["threaten", "flee", "call_for_help"]
        return constraints
