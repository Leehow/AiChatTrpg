"""Compile NPC state into compact behavior policies for the scene prompt."""

from __future__ import annotations

from typing import Any

from .common import clamp, get_value, text_blob
from .expression_mask import ExpressionMaskEngine
from .liveness_card import liveness_card_from_npc
from .memory_salience import retrieve_salient_memories
from .models import BehaviorPolicy, LatencyBudget, LivenessCard, SalientMemory


class BehaviorPolicyCompiler:
    def __init__(self, expression_engine: ExpressionMaskEngine | None = None) -> None:
        self.expression_engine = expression_engine or ExpressionMaskEngine()

    def compile(
        self,
        *,
        npc: Any | None,
        profile: Any,
        state: Any,
        relationship: Any | None,
        player_text: str = "",
        recent_events: list[Any] | None = None,
        liveness: LivenessCard | None = None,
        salient_memories: list[SalientMemory] | None = None,
    ) -> BehaviorPolicy:
        npc_id = str(get_value(profile, "npc_id") or get_value(state, "npc_id") or get_value(npc, "key") or "unknown_npc")
        liveness = liveness or liveness_card_from_npc(npc or {}, profile)
        mask = self.expression_engine.compile(profile=profile, state=state, relationship=relationship, liveness=liveness)
        salient_memories = salient_memories if salient_memories is not None else retrieve_salient_memories(
            npc or {}, player_text=player_text, recent_events=recent_events or [], limit=3,
        )

        mood = get_value(state, "mood") or {}
        goal_pressure = get_value(state, "goal_pressure") or {}
        persona = get_value(profile, "persona") or {}
        rel = relationship or {}
        fear = _num(mood, "fear")
        anger = _num(mood, "anger")
        suspicion = _num(mood, "suspicion")
        stress = _num(mood, "stress")
        curiosity = _num(mood, "curiosity")
        protect_secret = _num(goal_pressure, "protect_secret")
        trust = _num(rel, "trust", 0.35)
        respect = _num(rel, "respect", 0.35)
        hostility = _num(rel, "hostility", 0.0)
        dominance = _num(persona, "dominance", 0.4)
        deception_skill = _num(persona, "deception_skill", 0.35)
        impulse_control = _num(persona, "impulse_control", 0.5)

        cooperation = clamp(0.32 + trust * 0.35 + respect * 0.12 - suspicion * 0.18 - protect_secret * 0.2)
        deception = clamp(0.18 + deception_skill * 0.35 + protect_secret * 0.32 + suspicion * 0.18)
        aggression = clamp(0.08 + anger * 0.32 + dominance * 0.18 + hostility * 0.25 - impulse_control * 0.1)
        risk = clamp(0.22 + dominance * 0.2 + trust * 0.1 - fear * 0.25 - stress * 0.15)
        proactivity = clamp(liveness.proactivity + curiosity * 0.12 + aggression * 0.08 - fear * 0.08)
        interrupt_threshold = clamp(liveness.interrupt_threshold - aggression * 0.2 + stress * 0.08)

        tactics: list[str] = []
        avoided: list[str] = ["full_confession", "unmotivated_attack", "explain_inner_state_directly"]
        if protect_secret > 0.55 or suspicion > 0.6:
            tactics.extend(["deflect", "ask_counter_question", "move_private"])
        if trust > 0.55 and fear > 0.35:
            tactics.extend(["ask_for_protection", "reveal_minor_hint"])
        if anger > 0.55 and dominance > 0.45:
            tactics.extend(["set_boundary", "warn_consequences"])
        if fear > 0.72 and impulse_control < 0.45:
            tactics.extend(["panic_lie", "seek_exit"])
        if not tactics:
            tactics.extend(["observe", "answer_briefly"])

        for memory in salient_memories:
            blob = text_blob(memory.content, memory.tags)
            if "保护" in blob or "help" in blob or "save" in blob:
                cooperation = clamp(cooperation + 0.08)
            if "威胁" in blob or "attack" in blob or "threat" in blob:
                suspicion = clamp(suspicion + 0.08)
                tactics.append("keep_distance")

        dominant_state = _dominant_state(fear=fear, anger=anger, suspicion=suspicion, stress=stress, curiosity=curiosity)
        return BehaviorPolicy(
            npc_id=npc_id,
            dominant_state=dominant_state,
            visible_expression=mask.visible_expression,
            social_mask=mask.social_mask,
            cooperation_level=round(cooperation, 4),
            deception_level=round(deception, 4),
            aggression_level=round(aggression, 4),
            risk_tolerance=round(risk, 4),
            proactivity=round(proactivity, 4),
            interrupt_threshold=round(interrupt_threshold, 4),
            preferred_tactics=list(dict.fromkeys(tactics))[:6],
            avoided_tactics=avoided,
            dialogue_guidance={
                **mask.voice_guidance,
                "directness": _directness(cooperation, deception),
                "should_not": avoided,
            },
            body_language_guidance=mask.body_language[:3],
            memory_influences=[
                {
                    "memory_id": memory.memory_id,
                    "effect": memory.influence,
                }
                for memory in salient_memories[:3]
            ],
        )


def compile_policies_for_active_npcs(
    *,
    active_npcs: list[Any],
    profiles_by_id: dict[str, Any],
    states_by_id: dict[str, Any],
    relationships_by_npc: dict[str, dict[str, Any]] | None,
    player_text: str,
    recent_events: list[Any] | None,
    budget: LatencyBudget | None = None,
) -> dict[str, BehaviorPolicy]:
    budget = budget or LatencyBudget()
    compiler = BehaviorPolicyCompiler()
    policies: dict[str, BehaviorPolicy] = {}
    by_id = {str(get_value(npc, "key") or get_value(npc, "npc_id") or ""): npc for npc in active_npcs or []}
    candidate_ids = list(profiles_by_id)[: max(0, budget.max_foreground_npcs)]
    for npc_id in candidate_ids:
        profile = profiles_by_id.get(npc_id)
        state = states_by_id.get(npc_id)
        if not profile or not state:
            continue
        npc = by_id.get(npc_id, {})
        relationship = (relationships_by_npc or {}).get(npc_id, {}).get("pc")
        salient = retrieve_salient_memories(npc, player_text=player_text, recent_events=recent_events or [], limit=budget.max_salient_memories_per_npc)
        policies[npc_id] = compiler.compile(
            npc=npc,
            profile=profile,
            state=state,
            relationship=relationship,
            player_text=player_text,
            recent_events=recent_events or [],
            salient_memories=salient,
        )
    return policies


def _num(obj: Any, key: str, default: float = 0.0) -> float:
    return clamp(get_value(obj, key, default), default=default)


def _dominant_state(*, fear: float, anger: float, suspicion: float, stress: float, curiosity: float) -> str:
    values = {
        "fear": fear,
        "anger": anger,
        "suspicion": suspicion,
        "stress": stress,
        "curiosity": curiosity,
    }
    name, value = max(values.items(), key=lambda item: item[1])
    if value < 0.32:
        return "baseline"
    if name == "stress" and suspicion > 0.55:
        return "guarded_stress"
    return name


def _directness(cooperation: float, deception: float) -> str:
    if deception > 0.68:
        return "low"
    if cooperation > 0.62:
        return "medium_high"
    if cooperation < 0.3:
        return "low"
    return "medium"
