"""NPC planning interfaces and a deterministic fallback planner."""
from __future__ import annotations

from typing import Protocol

from .behavior_policy import BehaviorPolicyCompiler
from .models import (
    ActionProposal,
    ActionType,
    BehaviorPolicy,
    NPCIntentCard,
    NPCPerceptionPacket,
    NPCProfile,
    NPCState,
)
from .utils import new_id


class NPCPlanner(Protocol):
    def plan_cards(
        self,
        profile: NPCProfile,
        state: NPCState,
        packet: NPCPerceptionPacket | None,
        based_on_turn_id: int,
    ) -> list[NPCIntentCard]:
        ...


class RuleBasedNPCPlanner:
    """Cheap fallback planner for background/minor NPCs or LLM timeout."""

    def __init__(self):
        self.policy_compiler = BehaviorPolicyCompiler()

    def plan_cards(
        self,
        profile: NPCProfile,
        state: NPCState,
        packet: NPCPerceptionPacket | None,
        based_on_turn_id: int,
    ) -> list[NPCIntentCard]:
        policy = self.policy_compiler.compile(profile, state, packet.relationship_snapshot if packet else {})
        return [self._build_primary_card(profile, state, policy, based_on_turn_id)]

    def _build_primary_card(self, profile: NPCProfile, state: NPCState, policy: BehaviorPolicy, turn_id: int) -> NPCIntentCard:
        triggers = ["player_targets_npc", "player_asks_sensitive_question", "player_mentions_secret"]
        if profile.narrative_role == "gatekeeper":
            triggers.append("player_attempts_to_leave")
        if policy.aggression_level > 0.60:
            action_type = ActionType.SAY
            intent = "warn_or_pressure_players"
            speech_intent = "警告玩家不要继续逼近；若玩家继续升级，才进入规则冲突。"
            emote = "NPC的姿态变得强硬，像是在压住怒意。"
        elif policy.deception_level > 0.60:
            action_type = ActionType.DECEIVE
            intent = "protect_secret_with_partial_truth"
            speech_intent = "用半真半假的说法回应，避免具体人名、地点和核心秘密。"
            emote = "NPC避开关键问题，转而观察玩家反应。"
        elif policy.cooperation_level > 0.60:
            action_type = ActionType.SAY
            intent = "offer_limited_help"
            speech_intent = "愿意提供一个安全范围内的小线索或建议。"
            emote = "NPC稍微放松，但仍注意周围环境。"
        else:
            action_type = ActionType.DELAY
            intent = "delay_and_probe"
            speech_intent = "先试探玩家知道多少，再决定是否继续谈。"
            emote = "NPC沉默片刻，像是在权衡风险。"

        proposal = ActionProposal(
            actor_id=profile.npc_id,
            intent=intent,
            action_type=action_type,
            priority=0.55,
            player_facing={"speech_intent": speech_intent, "emote": emote},
            gm_facing={
                "decision_summary": f"Fallback planner based on policy: {policy.strategy_summary}",
                "dominant_mood": policy.dominant_mood,
            },
            forbidden_fact_ids=list(profile.plot_constraints.forbidden_fact_ids + profile.plot_constraints.core_secret_ids),
        )
        return NPCIntentCard(
            card_id=new_id("intent"),
            npc_id=profile.npc_id,
            based_on_turn_id=turn_id,
            valid_until_turn=turn_id + 3,
            priority=proposal.priority,
            trigger_conditions=triggers,
            preferred_action=proposal,
            motivation=policy.strategy_summary,
            known_fact_ids=list(profile.knowledge_fact_ids),
            forbidden_fact_ids=list(profile.plot_constraints.forbidden_fact_ids + profile.plot_constraints.core_secret_ids),
            plot_constraints=profile.plot_constraints,
        )


class LLMNPCPlanner:
    """Adapter shell for your existing NPC agent.

    Inject a callable with signature:
        callable(profile, state, packet) -> list[NPCIntentCard] | list[ActionProposal]

    Keep the callable timeout outside this class in your async runtime, or use the
    integration example provided in integration_examples/agent_adapter.py.
    """

    def __init__(self, planner_callable):
        self.planner_callable = planner_callable

    def plan_cards(
        self,
        profile: NPCProfile,
        state: NPCState,
        packet: NPCPerceptionPacket | None,
        based_on_turn_id: int,
    ) -> list[NPCIntentCard]:
        result = self.planner_callable(profile, state, packet)
        cards: list[NPCIntentCard] = []
        for item in result:
            if isinstance(item, NPCIntentCard):
                cards.append(item)
            elif isinstance(item, ActionProposal):
                cards.append(NPCIntentCard(
                    card_id=new_id("intent"),
                    npc_id=profile.npc_id,
                    based_on_turn_id=based_on_turn_id,
                    valid_until_turn=based_on_turn_id + 2,
                    priority=item.priority,
                    trigger_conditions=["player_targets_npc", "player_asks_sensitive_question"],
                    preferred_action=item,
                    motivation=str(item.gm_facing.get("decision_summary", item.intent)),
                    known_fact_ids=item.known_fact_ids,
                    forbidden_fact_ids=item.forbidden_fact_ids,
                    plot_constraints=profile.plot_constraints,
                ))
        return cards
