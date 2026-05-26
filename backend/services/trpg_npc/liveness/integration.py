"""Integration facade for NPC Runtime V2 liveness.

Foreground contract:
- deterministic only
- no LLM call
- no DB write
- capped active NPC/memory/beat counts

Background contract:
- liveness card enrichment, routine ticks, long memory compaction and richer
  planning can run after the visible GM reply.
"""

from __future__ import annotations

from typing import Any

from .behavior_policy import BehaviorPolicyCompiler
from .common import get_value, set_value
from .expression_mask import ExpressionMaskEngine
from .hot_patch_preview import apply_hot_patches_preview
from .liveness_card import liveness_card_from_npc
from .liveness_tick import LivenessTickEngine
from .memory_salience import retrieve_salient_memories
from .models import LatencyBudget, LivenessPreTurnBundle
from .mode_transition import preview_mode


def build_liveness_pre_turn_bundle(
    *,
    active_npcs: list[Any],
    profiles_by_id: dict[str, Any],
    states_by_id: dict[str, Any],
    relationships_by_npc: dict[str, dict[str, Any]] | None,
    hot_patches: list[Any] | None,
    player_text: str,
    recent_events: list[Any] | None,
    budget: LatencyBudget | None = None,
) -> tuple[dict[str, Any], LivenessPreTurnBundle]:
    """Return effective foreground states and prompt metadata bundle."""

    budget = budget or LatencyBudget()
    effective_states = apply_hot_patches_preview(states_by_id, hot_patches or [])
    bundle = LivenessPreTurnBundle(metadata={
        "foreground_mode": "deterministic_liveness_v1",
        "max_foreground_npcs": budget.max_foreground_npcs,
        "max_liveness_beats": budget.max_liveness_beats,
        "background_hint": "LLM enrichment/routine planning should run after the visible reply.",
    })
    expression_engine = ExpressionMaskEngine()
    policy_compiler = BehaviorPolicyCompiler(expression_engine)
    by_id = {str(get_value(npc, "key") or get_value(npc, "npc_id") or ""): npc for npc in active_npcs or []}

    for npc_id in list(profiles_by_id)[: max(0, budget.max_foreground_npcs)]:
        profile = profiles_by_id.get(npc_id)
        state = effective_states.get(npc_id)
        if not profile or not state:
            continue
        npc = by_id.get(npc_id, {})
        rels = relationships_by_npc.get(npc_id, {}) if relationships_by_npc else {}
        relationship = rels.get("pc") or rels.get("player") or next(iter(rels.values()), None)
        liveness = liveness_card_from_npc(npc, profile)
        mode = preview_mode(profile, state, relationship, recent_events or [])
        _set_preview_mode(state, mode)
        salient = retrieve_salient_memories(
            npc,
            player_text=player_text,
            recent_events=recent_events or [],
            limit=budget.max_salient_memories_per_npc,
        )
        mask = expression_engine.compile(profile=profile, state=state, relationship=relationship, liveness=liveness)
        policy = policy_compiler.compile(
            npc=npc,
            profile=profile,
            state=state,
            relationship=relationship,
            player_text=player_text,
            recent_events=recent_events or [],
            liveness=liveness,
            salient_memories=salient,
        )
        bundle.expression_masks_by_npc[npc_id] = mask
        bundle.salient_memories_by_npc[npc_id] = salient
        bundle.policies_by_npc[npc_id] = policy

    bundle.liveness_beats = LivenessTickEngine().select_beats(
        policies_by_npc=bundle.policies_by_npc,
        active_npcs=active_npcs,
        recent_events=recent_events or [],
        budget=budget,
    )
    return effective_states, bundle


def attach_liveness_to_beat_plan(beat_plan: Any, bundle: LivenessPreTurnBundle) -> None:
    metadata = get_value(beat_plan, "metadata")
    if metadata is None or not isinstance(metadata, dict):
        metadata = {}
        set_value(beat_plan, "metadata", metadata)
    metadata["npc_liveness"] = bundle.to_prompt_metadata()

    # Help older prompt renderers notice the liveness beats even if they do not
    # inspect metadata deeply.
    optional_beats = get_value(beat_plan, "optional_beats")
    if isinstance(optional_beats, list):
        for beat in bundle.liveness_beats:
            optional_beats.append({
                "type": f"NPC_LIVENESS_{beat.beat_type.value.upper()}",
                "npc_id": beat.npc_id,
                "beat": beat.beat,
                "consumes_primary_action": beat.consumes_primary_action,
                "priority": beat.priority,
            })


def _set_preview_mode(state: Any, mode: str) -> None:
    if not mode:
        return
    set_value(state, "current_mode", mode)
