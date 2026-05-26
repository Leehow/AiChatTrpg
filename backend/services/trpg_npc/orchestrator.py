"""Foreground/background orchestration for the optimized NPC runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .action_board import ActionBoard
from .action_resolver import ActionResolver
from .activator import NPCActivator
from .appraiser import EventAppraiser
from .context_builder import NPCContextBuilder
from .hot_state_patch import HotStatePatchEngine
from .liveness import (
    LatencyBudget,
    attach_liveness_to_beat_plan,
    build_liveness_pre_turn_bundle,
)
from .memory import MemoryWriter
from .models import (
    ActionProposal,
    GameEvent,
    HotStatePatch,
    MemoryRecord,
    NPCProfile,
    NPCState,
    RelationshipVector,
    SceneBeatPlan,
    SceneState,
)
from .npc_planner import NPCPlanner, RuleBasedNPCPlanner
from .plot_integrator import PlotIntegrator
from .state_updater import StateVectorUpdater


@dataclass(slots=True)
class PreTurnResult:
    beat_plan: SceneBeatPlan
    hot_patches: list[HotStatePatch] = field(default_factory=list)
    matched_card_ids: list[str] = field(default_factory=list)
    hot_npc_ids: list[str] = field(default_factory=list)
    action_board_matches: list[dict[str, Any]] = field(default_factory=list)
    action_board_resolutions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PostTurnResult:
    updated_states: dict[str, NPCState] = field(default_factory=dict)
    updated_relationships: dict[str, dict[str, RelationshipVector]] = field(default_factory=dict)
    new_memories: list[MemoryRecord] = field(default_factory=list)
    planned_card_ids: list[str] = field(default_factory=list)


class NPCTurnOrchestrator:
    """Hybrid architecture: background ActionBoard + foreground thin arbitration."""

    def __init__(
        self,
        action_board: ActionBoard | None = None,
        planner: NPCPlanner | None = None,
        max_hot_npcs: int = 1,
    ):
        self.action_board = action_board or ActionBoard()
        self.planner = planner or RuleBasedNPCPlanner()
        self.max_hot_npcs = max_hot_npcs
        self.activator = NPCActivator()
        self.patch_engine = HotStatePatchEngine()
        self.resolver = ActionResolver()
        self.integrator = PlotIntegrator()
        self.context_builder = NPCContextBuilder()
        self.appraiser = EventAppraiser()
        self.state_updater = StateVectorUpdater()
        self.memory_writer = MemoryWriter()

    def pre_turn(
        self,
        scene_state: SceneState,
        player_event: GameEvent,
        profiles_by_id: dict[str, NPCProfile],
        states_by_id: dict[str, NPCState],
        relationships_by_npc: dict[str, dict[str, RelationshipVector]] | None = None,
        recent_events: list[GameEvent] | None = None,
        scene_tags: list[str] | None = None,
        active_npcs: list[Any] | None = None,
        liveness_budget: LatencyBudget | None = None,
    ) -> PreTurnResult:
        relationships_by_npc = relationships_by_npc or {}
        recent_events = recent_events or [player_event]
        active = set(scene_state.active_npc_ids)

        self.action_board.expire_old(scene_state.scene_id, scene_state.turn_id)
        matches = self.action_board.match(
            scene_state.scene_id,
            player_event,
            active_npc_ids=active,
            events=recent_events,
        )
        matched_card_ids = [m.card.card_id for m in matches]
        match_observations = [_match_observation(match) for match in matches]

        hot_patches: list[HotStatePatch] = []
        affected_npc_ids = set(player_event.target_ids + [m.card.npc_id for m in matches])
        for npc_id in affected_npc_ids:
            profile = profiles_by_id.get(npc_id)
            state = states_by_id.get(npc_id)
            if not profile or not state:
                continue
            rel = relationships_by_npc.get(npc_id, {}).get(player_event.actor_id or "")
            hot_patches.append(self.patch_engine.patch_for_event(player_event, profile, state, rel, scene_tags=scene_tags))

        liveness_bundle = None
        liveness_error = ""
        effective_states: dict[str, Any] = dict(states_by_id)
        try:
            effective_states, liveness_bundle = build_liveness_pre_turn_bundle(
                active_npcs=active_npcs or [
                    {"key": npc_id}
                    for npc_id in scene_state.active_npc_ids
                ],
                profiles_by_id=profiles_by_id,
                states_by_id=states_by_id,
                relationships_by_npc=relationships_by_npc,
                hot_patches=hot_patches,
                player_text=player_event.content or "",
                recent_events=recent_events,
                budget=liveness_budget or LatencyBudget(),
            )
        except Exception as exc:  # pragma: no cover - foreground must degrade
            effective_states = dict(states_by_id)
            liveness_error = f"{type(exc).__name__}: {exc}"

        hot_npc_ids = self.activator.select_hot_npcs(
            scene_state,
            player_event,
            profiles_by_id,
            matches,
            max_count=self.max_hot_npcs,
        )

        proposals: list[ActionProposal] = self.action_board.proposals_from_matches(matches)

        # Fallback / sync-hot planning. In production this may call your LLM agent
        # with a short timeout; this implementation stays deterministic.
        for npc_id in hot_npc_ids:
            profile = profiles_by_id[npc_id]
            state = effective_states.get(npc_id, states_by_id[npc_id])
            packet = self.context_builder.build(
                npc_id,
                scene_state,
                recent_events,
                profile,
                relationships=relationships_by_npc.get(npc_id, {}),
            )
            cards = self.planner.plan_cards(profile, state, packet, based_on_turn_id=scene_state.turn_id)
            # Do not persist these foreground cards automatically; just use the proposal.
            proposals.extend(card.preferred_action for card in cards)

        resolved = self.resolver.resolve(proposals, scene_state, profiles_by_id)
        resolution_observations = [
            _resolution_observation(action)
            for action in resolved
            if _source_card_id(action)
        ]
        beat_plan = self.integrator.build_scene_beat_plan(scene_state, player_event, resolved)
        if liveness_bundle is not None:
            attach_liveness_to_beat_plan(beat_plan, liveness_bundle)
        elif liveness_error:
            beat_plan.metadata["npc_liveness"] = {
                "foreground_mode": "disabled",
                "error": liveness_error,
            }
        return PreTurnResult(
            beat_plan=beat_plan,
            hot_patches=hot_patches,
            matched_card_ids=matched_card_ids,
            hot_npc_ids=hot_npc_ids,
            action_board_matches=match_observations,
            action_board_resolutions=resolution_observations,
        )

    def post_turn(
        self,
        scene_state: SceneState,
        committed_events: list[GameEvent],
        profiles_by_id: dict[str, NPCProfile],
        states_by_id: dict[str, NPCState],
        relationships_by_npc: dict[str, dict[str, RelationshipVector]] | None = None,
        scene_tags: list[str] | None = None,
        plan_for_next_turn: bool = True,
    ) -> PostTurnResult:
        relationships_by_npc = relationships_by_npc or {}
        result = PostTurnResult()
        affected: set[str] = set()

        for event in committed_events:
            affected.update(event.target_ids)
            if event.actor_id in profiles_by_id:
                affected.add(event.actor_id)
            # Active major/supporting NPCs who can hear the event get light updates.
            for npc_id in scene_state.active_npc_ids:
                profile = profiles_by_id.get(npc_id)
                if profile and profile.tier.value in {"L2_SUPPORTING", "L3_MAJOR"}:
                    affected.add(npc_id)

        for npc_id in affected:
            profile = profiles_by_id.get(npc_id)
            state = states_by_id.get(npc_id)
            if not profile or not state:
                continue
            npc_relationships = relationships_by_npc.setdefault(npc_id, {})
            for event in committed_events:
                rel = npc_relationships.get(event.actor_id or "")
                appraisal = self.appraiser.appraise(event, profile, state, rel, scene_tags=scene_tags)
                state, npc_relationships = self.state_updater.apply(
                    profile,
                    state,
                    appraisal,
                    actor_id=event.actor_id,
                    relationships=npc_relationships,
                    commit=True,
                )
                memory = self.memory_writer.write_from_event(npc_id, event, importance=appraisal.magnitude())
                if memory:
                    result.new_memories.append(memory)
            result.updated_states[npc_id] = state
            result.updated_relationships[npc_id] = npc_relationships

            if plan_for_next_turn and npc_id in scene_state.active_npc_ids:
                packet = self.context_builder.build(npc_id, scene_state, committed_events, profile, npc_relationships)
                cards = self.planner.plan_cards(profile, state, packet, based_on_turn_id=scene_state.turn_id)
                self.action_board.upsert(scene_state.scene_id, cards)
                result.planned_card_ids.extend(card.card_id for card in cards)

        return result


def _match_observation(match: Any) -> dict[str, Any]:
    """Compact, secret-free debug payload for one ActionBoard card match."""

    card = match.card
    proposal = card.preferred_action
    metadata = card.metadata if isinstance(card.metadata, dict) else {}
    gm_facing = proposal.gm_facing if isinstance(proposal.gm_facing, dict) else {}
    return {
        "card_id": card.card_id,
        "npc_id": card.npc_id,
        "planner": str(metadata.get("planner") or gm_facing.get("planner") or "rule_based"),
        "intent": proposal.intent,
        "action_type": proposal.action_type.value,
        "matched_triggers": list(match.matched_triggers),
        "score": round(float(match.score or 0.0), 4),
        "priority": round(float(card.priority or 0.0), 4),
        "based_on_turn_id": int(card.based_on_turn_id or 0),
        "valid_until_turn": int(card.valid_until_turn or 0),
    }


def _resolution_observation(action: Any) -> dict[str, Any]:
    """Compact ActionResolver result for an ActionBoard-sourced proposal."""

    proposal = action.proposal
    source_card_id = _source_card_id(action)
    transformed_from = action.transformed_from
    return {
        "card_id": source_card_id,
        "npc_id": proposal.actor_id,
        "intent": proposal.intent,
        "action_type": proposal.action_type.value,
        "decision": action.decision.value,
        "reason": action.reason,
        "transformed_from_action_type": (
            transformed_from.action_type.value
            if transformed_from is not None
            else ""
        ),
    }


def _source_card_id(action: Any) -> str:
    proposal_source = getattr(action.proposal, "source_card_id", None)
    if proposal_source:
        return str(proposal_source)
    transformed_from = getattr(action, "transformed_from", None)
    transformed_source = getattr(transformed_from, "source_card_id", None)
    return str(transformed_source or "")
