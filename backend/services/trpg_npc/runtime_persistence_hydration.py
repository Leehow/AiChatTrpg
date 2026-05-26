"""JSON-to-domain decoders for NPC Runtime V2 persistence.

Used when hydrating table rows back into the dataclass domain model so that
the orchestrator and adapters can work with familiar types.
"""

from __future__ import annotations

from typing import Any

from services.trpg_npc.models import (
    MoodVector,
    NPCMode,
    NPCProfile,
    NPCState,
    NPCTier,
    PersonaVector,
    PlotConstraints,
    RelationshipVector,
    VoiceCard,
)
from services.trpg_npc.runtime_persistence_helpers import (
    _dict,
    _float,
    _float_dict,
    _int,
    _list_strings,
    _str_dict,
)


def _profile_from_json(raw: dict[str, Any], *, fallback: NPCProfile) -> NPCProfile:
    if not raw:
        return fallback
    modes = [
        _mode_from_json(item)
        for item in raw.get("modes", [])
        if isinstance(item, dict)
    ]
    profile = NPCProfile(
        npc_id=str(raw.get("npc_id") or fallback.npc_id),
        name=str(raw.get("name") or fallback.name),
        tier=_tier(raw.get("tier"), fallback.tier),
        narrative_role=str(raw.get("narrative_role") or fallback.narrative_role),
        anchor=_dict(raw.get("anchor")) or dict(fallback.anchor),
        public_card=_str_dict(raw.get("public_card")) or dict(fallback.public_card),
        private_card=_str_dict(raw.get("private_card")) or dict(fallback.private_card),
        persona=_persona_from_json(raw.get("persona"), fallback=fallback.persona),
        baseline_mood=_mood_from_json(raw.get("baseline_mood"), fallback=fallback.baseline_mood),
        voice_card=_voice_card_from_json(raw.get("voice_card"), fallback=fallback.voice_card),
        modes=modes or list(fallback.modes),
        plot_constraints=_plot_constraints_from_json(
            raw.get("plot_constraints"),
            fallback=fallback.plot_constraints,
        ),
        mechanics=_dict(raw.get("mechanics")) or dict(fallback.mechanics),
        knowledge_fact_ids=_list_strings(raw.get("knowledge_fact_ids")) or list(fallback.knowledge_fact_ids),
        secret_ids=_list_strings(raw.get("secret_ids")) or list(fallback.secret_ids),
        tags=_list_strings(raw.get("tags")) or list(fallback.tags),
    )
    if _tier_rank(fallback.tier) > _tier_rank(profile.tier):
        profile.tier = fallback.tier
    if profile.narrative_role in {"", "ambient"} and fallback.narrative_role not in {"", "ambient"}:
        profile.narrative_role = fallback.narrative_role
    return profile


def _state_from_json(raw: dict[str, Any], *, fallback: NPCState) -> NPCState:
    if not raw:
        return fallback
    state = NPCState(
        npc_id=str(raw.get("npc_id") or fallback.npc_id),
        scene_id=str(raw.get("scene_id") or fallback.scene_id or ""),
        location_id=str(raw.get("location_id") or fallback.location_id or ""),
        status=str(raw.get("status") or fallback.status),
        current_mode=str(raw.get("current_mode") or fallback.current_mode),
        mood=_mood_from_json(raw.get("mood"), fallback=fallback.mood),
        goal_pressure=_float_dict(raw.get("goal_pressure")) or dict(fallback.goal_pressure),
        physical_state=_dict(raw.get("physical_state")) or dict(fallback.physical_state),
        active_flags=_dict(raw.get("active_flags")) or dict(fallback.active_flags),
        state_version=_int(raw.get("state_version")) or fallback.state_version,
    )
    if isinstance(raw.get("updated_at"), str) and raw["updated_at"].strip():
        state.updated_at = raw["updated_at"].strip()
    return state


def _relationship_from_json(raw: dict[str, Any], *, fallback: RelationshipVector) -> RelationshipVector:
    data = fallback.to_dict()
    for key in data:
        if key in raw:
            data[key] = _float(raw.get(key), default=data[key])
    return RelationshipVector(**data).normalized()


def _mood_from_json(raw: Any, *, fallback: MoodVector) -> MoodVector:
    data = fallback.to_dict()
    if isinstance(raw, dict):
        for key in data:
            if key in raw:
                data[key] = _float(raw.get(key), default=data[key])
    return MoodVector(**data).normalized()


def _persona_from_json(raw: Any, *, fallback: PersonaVector) -> PersonaVector:
    data = fallback.to_dict()
    if isinstance(raw, dict):
        for key in data:
            if key in raw:
                data[key] = _float(raw.get(key), default=data[key])
    return PersonaVector(**data).normalized()


def _voice_card_from_json(raw: Any, *, fallback: VoiceCard) -> VoiceCard:
    if not isinstance(raw, dict):
        return fallback
    return VoiceCard(
        tone=str(raw.get("tone") or fallback.tone),
        register=str(raw.get("register") or fallback.register),
        sentence_length=str(raw.get("sentence_length") or fallback.sentence_length),
        catchphrases=_list_strings(raw.get("catchphrases")) or list(fallback.catchphrases),
        forbidden_style=_list_strings(raw.get("forbidden_style")) or list(fallback.forbidden_style),
        examples=_list_strings(raw.get("examples")) or list(fallback.examples),
        address_style=_str_dict(raw.get("address_style")) or dict(fallback.address_style),
    )


def _mode_from_json(raw: dict[str, Any]) -> NPCMode:
    return NPCMode(
        mode_id=str(raw.get("mode_id") or "default"),
        title=str(raw.get("title") or "Default"),
        description=str(raw.get("description") or ""),
        visible_expression=str(raw.get("visible_expression") or "neutral"),
        tone_bias=str(raw.get("tone_bias") or ""),
        trigger_conditions=_list_strings(raw.get("trigger_conditions")),
        policy_bias=_float_dict(raw.get("policy_bias")),
    )


def _plot_constraints_from_json(raw: Any, *, fallback: PlotConstraints) -> PlotConstraints:
    if not isinstance(raw, dict):
        return fallback
    return PlotConstraints(
        can_reveal_core_secret=bool(raw.get("can_reveal_core_secret", fallback.can_reveal_core_secret)),
        can_attack_players=str(raw.get("can_attack_players") or fallback.can_attack_players),
        can_flee=bool(raw.get("can_flee", fallback.can_flee)),
        must_preserve_clue_path=bool(raw.get("must_preserve_clue_path", fallback.must_preserve_clue_path)),
        max_clue_reveals_per_turn=_int(raw.get("max_clue_reveals_per_turn")) or fallback.max_clue_reveals_per_turn,
        minimum_clue_output=raw.get("minimum_clue_output") if isinstance(raw.get("minimum_clue_output"), str) else fallback.minimum_clue_output,
        forbidden_fact_ids=_list_strings(raw.get("forbidden_fact_ids")) or list(fallback.forbidden_fact_ids),
        core_secret_ids=_list_strings(raw.get("core_secret_ids")) or list(fallback.core_secret_ids),
        blocked_escalations=_list_strings(raw.get("blocked_escalations")) or list(fallback.blocked_escalations),
        allowed_escalations=_list_strings(raw.get("allowed_escalations")) or list(fallback.allowed_escalations),
    )


def _tier(value: Any, fallback: NPCTier) -> NPCTier:
    raw = str(value or "").strip()
    for tier in NPCTier:
        if raw in {tier.name, tier.value}:
            return tier
    return fallback


def _tier_rank(tier: NPCTier) -> int:
    order = {
        NPCTier.BACKGROUND: 0,
        NPCTier.MINOR: 1,
        NPCTier.SUPPORTING: 2,
        NPCTier.MAJOR: 3,
        NPCTier.FACTION: 4,
    }
    return order.get(tier, 0)
