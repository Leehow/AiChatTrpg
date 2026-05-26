"""Adapt session-JSON NPC records into NPC Runtime V2 profile/state contracts."""

from __future__ import annotations

import re
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
    VoiceCard as RuntimeVoiceCard,
)
from services.trpg_npc.runtime_adapter_coerce import (
    _float_dict,
    _int,
    _list_strings,
    _mood_vector_from_dict,
    _plain_dict,
    _relationship_vector_from_dict,
)


def _adapt_npc(npc: dict[str, Any], *, scene_id: str) -> tuple[NPCProfile, NPCState, RelationshipVector]:
    npc_id = _npc_id(npc)
    narrative_role = _narrative_role(npc)
    tier = _npc_tier(npc, narrative_role)
    secret_ids = _secret_ids(npc, npc_id)
    profile = NPCProfile(
        npc_id=npc_id,
        name=str(npc.get("name") or npc.get("player_known_name") or npc_id),
        tier=tier,
        narrative_role=narrative_role,
        anchor={
            "scene_id": str(npc.get("last_seen_scene") or scene_id),
            "location_id": str(npc.get("location_id") or scene_id),
        },
        public_card=_public_card(npc),
        private_card=_private_card(npc),
        persona=_persona(npc, narrative_role),
        baseline_mood=_mood_from_npc(npc),
        voice_card=_runtime_voice_card(npc),
        modes=_modes_for_role(narrative_role),
        plot_constraints=_plot_constraints(npc, secret_ids, narrative_role),
        mechanics=dict(npc.get("params") or {}) if isinstance(npc.get("params"), dict) else {},
        knowledge_fact_ids=_list_strings(npc.get("knowledge_fact_ids")),
        secret_ids=secret_ids,
        tags=_list_strings(npc.get("tags")),
    )
    state = _state_from_npc(npc, profile=profile, scene_id=scene_id)
    return profile, state, _relationship_to_pc(npc)


def _npc_id(npc: dict[str, Any]) -> str:
    key = str(npc.get("key") or "").strip()
    if key:
        return key
    name = str(npc.get("name") or npc.get("player_known_name") or "npc").strip().lower()
    slug = re.sub(r"[^a-z0-9_一-鿿]+", "_", name).strip("_")
    return slug or "npc"


def _display_name(npc: dict[str, Any]) -> str:
    if npc.get("name_revealed"):
        return str(npc.get("name") or npc.get("player_known_name") or _npc_id(npc))
    return str(npc.get("player_known_name") or npc.get("public_name") or _npc_id(npc))


def _public_card(npc: dict[str, Any]) -> dict[str, str]:
    card: dict[str, str] = {}
    for key in ("role", "title", "summary", "description", "appearance", "player_known_name"):
        value = npc.get(key)
        if isinstance(value, str) and value.strip():
            card[key] = value.strip()
    return card


def _private_card(npc: dict[str, Any]) -> dict[str, str]:
    card: dict[str, str] = {}
    inner = npc.get("inner_state") if isinstance(npc.get("inner_state"), dict) else {}
    for key in ("secret_agenda", "motivation"):
        value = inner.get(key) or npc.get(key)
        if isinstance(value, str) and value.strip():
            card[key] = value.strip()
    return card


def _narrative_role(npc: dict[str, Any]) -> str:
    explicit = str(npc.get("narrative_role") or "").strip()
    if explicit:
        return explicit
    blob = _blob(npc)
    if any(w in blob for w in (
        "antagonist", "cultist", "enemy", "villain", "hostile", "monster",
        "predator", "threat", "ringleader", "leader",
        "反派", "邪教", "敌人", "怪物", "凶手", "杀手", "威胁",
        "危险", "残暴", "嗜血", "领袖", "首领", "头目", "地痞",
        "武力", "猎枪", "撬胎棒", "监视", "冒名顶替", "女祭司",
        "蛇人", "半蛇人", "眷属",
    )):
        return "antagonist"
    if any(w in blob for w in ("witness", "目击", "证人")):
        return "witness"
    if any(w in blob for w in (
        "clue", "informant", "contact", "file", "missing",
        "线索", "知道", "知情", "联系人", "信息来源", "档案", "失踪",
    )):
        return "clue_holder"
    if any(w in blob for w in (
        "guard", "gatekeeper", "block", "barrier",
        "守卫", "门卫", "老板", "店主", "拦住", "阻拦", "掌握局势",
    )):
        return "gatekeeper"
    if npc.get("from_bond") or any(w in blob for w in (
        "friend", "ally", "detective", "police", "contact",
        "朋友", "盟友", "警探", "警察", "旧识", "可靠信息来源",
    )):
        return "ally"
    return "ambient"


def _npc_tier(npc: dict[str, Any], narrative_role: str) -> NPCTier:
    raw = str(npc.get("tier") or npc.get("npc_tier") or "").strip()
    for tier in NPCTier:
        if raw in {tier.name, tier.value}:
            return tier
    if raw in {"L0", "background"}:
        return NPCTier.BACKGROUND
    if raw in {"L2", "supporting"}:
        return NPCTier.SUPPORTING
    if raw in {"L3", "major", "core"}:
        return NPCTier.MAJOR
    if narrative_role in {"clue_holder", "witness", "antagonist", "ally", "gatekeeper"}:
        return NPCTier.SUPPORTING
    return NPCTier.MINOR


def _persona(npc: dict[str, Any], narrative_role: str) -> PersonaVector:
    persona = PersonaVector()
    blob = _blob(npc)
    if narrative_role == "antagonist" or "secret_agenda" in blob:
        persona.paranoia = 0.6
        persona.deception_skill = 0.65
        persona.agreeableness = 0.3
    if any(w in blob for w in ("friendly", "kind", "友善", "温和")):
        persona.agreeableness = 0.7
        persona.empathy = 0.65
    if any(w in blob for w in ("guard", "警惕", "怀疑", "suspicious")):
        persona.paranoia = max(persona.paranoia, 0.55)
    return persona.normalized()


def _mood_from_npc(npc: dict[str, Any]) -> MoodVector:
    mood = MoodVector()
    inner = npc.get("inner_state") if isinstance(npc.get("inner_state"), dict) else {}
    text = " ".join(
        str(v)
        for v in (
            npc.get("emotional_state"),
            npc.get("personality"),
            inner.get("emotional_state"),
            inner.get("motivation"),
        )
        if v
    ).lower()
    if any(w in text for w in ("fear", "afraid", "scared", "害怕", "恐惧", "慌")):
        mood.fear = 0.6
        mood.stress = 0.55
    if any(w in text for w in ("suspicious", "wary", "guarded", "警惕", "怀疑", "戒备")):
        mood.suspicion = 0.6
        mood.stress = max(mood.stress, 0.35)
    if any(w in text for w in ("angry", "hostile", "furious", "愤怒", "生气", "敌意")):
        mood.anger = 0.6
        mood.valence = -0.4
    if any(w in text for w in ("curious", "好奇", "探究")):
        mood.curiosity = 0.65
    if any(w in text for w in ("friendly", "warm", "relaxed", "友善", "温和", "放松")):
        mood.joy = 0.35
        mood.valence = 0.35
    return mood.normalized()


def _relationship_to_pc(npc: dict[str, Any]) -> RelationshipVector:
    legacy = _legacy_relationship_to_pc(npc)
    raw_relationships = npc.get("relationships_v2")
    if isinstance(raw_relationships, dict):
        for key in ("pc", "player", "player_character"):
            raw = raw_relationships.get(key)
            if isinstance(raw, dict):
                return _relationship_vector_from_dict(raw, fallback=legacy)
    return legacy


def _legacy_relationship_to_pc(npc: dict[str, Any]) -> RelationshipVector:
    kn = npc.get("player_knowledge") if isinstance(npc.get("player_knowledge"), dict) else {}
    rel = RelationshipVector()
    relation = str(kn.get("relationship") or "").lower()
    if relation in {"preexisting_relationship", "ally", "friend"} or npc.get("from_bond"):
        rel.trust = 0.55
        rel.affinity = 0.35
    try:
        interest = int(kn.get("interest") or 3)
    except (TypeError, ValueError):
        interest = 3
    if interest >= 7:
        rel.suspicion = max(rel.suspicion, 0.45)
    elif interest <= 2:
        rel.suspicion = min(rel.suspicion, 0.2)
    return rel.normalized()


def _state_from_npc(npc: dict[str, Any], *, profile: NPCProfile, scene_id: str) -> NPCState:
    raw = npc.get("runtime_state_v2")
    if not isinstance(raw, dict):
        raw = {}
    fallback_mood = _mood_from_npc(npc)
    state = NPCState(
        npc_id=profile.npc_id,
        scene_id=str(raw.get("scene_id") or npc.get("last_seen_scene") or scene_id),
        location_id=str(raw.get("location_id") or npc.get("location_id") or scene_id),
        status=str(raw.get("status") or "active"),
        current_mode=str(raw.get("current_mode") or profile.default_mode_id()),
        mood=_mood_vector_from_dict(raw.get("mood"), fallback=fallback_mood),
        goal_pressure=_float_dict(raw.get("goal_pressure")) or _goal_pressure(npc, profile.secret_ids),
        physical_state=_plain_dict(raw.get("physical_state")),
        active_flags=_plain_dict(raw.get("active_flags")),
        state_version=_int(raw.get("state_version"), _int(npc.get("state_version"), 0)),
    )
    updated_at = raw.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        state.updated_at = updated_at.strip()
    return state


def _runtime_voice_card(npc: dict[str, Any]) -> RuntimeVoiceCard:
    card = npc.get("voice_card") if isinstance(npc.get("voice_card"), dict) else {}
    examples = card.get("sample_lines") if isinstance(card.get("sample_lines"), list) else []
    return RuntimeVoiceCard(
        tone=str(card.get("speaking_style") or card.get("tone") or "neutral"),
        register=str(card.get("register") or "plain"),
        sentence_length=str(card.get("sentence_length") or "medium"),
        catchphrases=[str(card.get("catchphrase"))] if card.get("catchphrase") else [],
        examples=[str(v) for v in examples[:2]],
    )


def _safe_voice_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in card.items()
        if key in {"speaking_style", "catchphrase", "mannerisms", "sample_lines", "tone", "register"}
    }


def _modes_for_role(narrative_role: str) -> list[NPCMode]:
    if narrative_role in {"antagonist", "gatekeeper"}:
        return [
            NPCMode("default", "Default", visible_expression="polite_but_guarded"),
            NPCMode("cornered", "Cornered", visible_expression="coldly_hostile"),
        ]
    return [NPCMode("default", "Default", visible_expression="neutral")]


def _plot_constraints(npc: dict[str, Any], secret_ids: list[str], narrative_role: str) -> PlotConstraints:
    constraints = PlotConstraints(
        forbidden_fact_ids=list(secret_ids),
        core_secret_ids=list(secret_ids),
    )
    if narrative_role in {"witness", "clue_holder"}:
        constraints.can_attack_players = "never"
    if narrative_role in {"antagonist", "gatekeeper"}:
        constraints.allowed_escalations = ["threaten", "flee", "call_for_help"]
    raw = npc.get("plot_constraints")
    if isinstance(raw, dict):
        if isinstance(raw.get("forbidden_fact_ids"), list):
            constraints.forbidden_fact_ids = _list_strings(raw.get("forbidden_fact_ids"))
        if isinstance(raw.get("core_secret_ids"), list):
            constraints.core_secret_ids = _list_strings(raw.get("core_secret_ids"))
        if isinstance(raw.get("can_reveal_core_secret"), bool):
            constraints.can_reveal_core_secret = raw["can_reveal_core_secret"]
        if isinstance(raw.get("can_attack_players"), str):
            constraints.can_attack_players = raw["can_attack_players"]
    return constraints


def _goal_pressure(npc: dict[str, Any], secret_ids: list[str]) -> dict[str, float]:
    pressure: dict[str, float] = {}
    inner = npc.get("inner_state") if isinstance(npc.get("inner_state"), dict) else {}
    if secret_ids or inner.get("secret_agenda"):
        pressure["protect_secret"] = 0.65
    if inner.get("motivation"):
        pressure["pursue_current_goal"] = 0.45
    return pressure


def _secret_ids(npc: dict[str, Any], npc_id: str) -> list[str]:
    out: list[str] = []
    for key in ("secret_ids", "forbidden_fact_ids", "core_secret_ids"):
        out.extend(_list_strings(npc.get(key)))
    inner = npc.get("inner_state") if isinstance(npc.get("inner_state"), dict) else {}
    if inner.get("secret_agenda"):
        out.append(f"secret:{npc_id}:agenda")
    return list(dict.fromkeys(out))


def _blob(npc: dict[str, Any]) -> str:
    inner = npc.get("inner_state") if isinstance(npc.get("inner_state"), dict) else {}
    pieces: list[str] = []
    for source in (npc, inner):
        for key in ("role", "title", "summary", "description", "personality", "motivation", "secret_agenda"):
            value = source.get(key)
            if isinstance(value, str):
                pieces.append(value.lower())
    return " ".join(pieces)
