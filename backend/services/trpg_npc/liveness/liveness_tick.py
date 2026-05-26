"""Foreground liveness beats.

A liveness beat adds presence without stealing the turn. Ambient/reaction beats
do not consume primary NPC action budget. Initiative beats are capped tightly
and should still flow through normal ActionResolver/PlotIntegrator if promoted
into a real action.
"""

from __future__ import annotations

from typing import Any

from .common import get_value, short_text
from .models import BehaviorPolicy, LatencyBudget, LivenessBeat, LivenessBeatType


class LivenessTickEngine:
    def select_beats(
        self,
        *,
        policies_by_npc: dict[str, BehaviorPolicy],
        active_npcs: list[Any],
        recent_events: list[Any] | None = None,
        budget: LatencyBudget | None = None,
    ) -> list[LivenessBeat]:
        budget = budget or LatencyBudget()
        beats: list[LivenessBeat] = []
        active_order = [str(get_value(npc, "key") or get_value(npc, "npc_id") or "") for npc in active_npcs or []]
        event_types = {str(get_value(ev, "type") or "") for ev in recent_events or []}

        for npc_id in active_order:
            policy = policies_by_npc.get(npc_id)
            if not policy:
                continue
            if policy.body_language_guidance:
                beats.append(LivenessBeat(
                    beat_type=LivenessBeatType.REACTION if event_types else LivenessBeatType.AMBIENT,
                    npc_id=npc_id,
                    beat=_reaction_text(policy),
                    priority=_priority(policy),
                    consumes_primary_action=False,
                    reason="surface_expression",
                ))
            if len(beats) >= budget.max_liveness_beats:
                break

        initiative_used = 0
        for npc_id, policy in policies_by_npc.items():
            if initiative_used >= budget.max_initiative_beats:
                break
            if policy.proactivity < 0.62 or policy.interrupt_threshold > 0.62:
                continue
            if any(tactic in policy.preferred_tactics for tactic in ["move_private", "set_boundary", "ask_for_protection"]):
                beats.append(LivenessBeat(
                    beat_type=LivenessBeatType.INITIATIVE,
                    npc_id=npc_id,
                    beat=_initiative_text(policy),
                    priority=min(0.9, policy.proactivity + 0.1),
                    consumes_primary_action=True,
                    reason="high_proactivity_policy",
                ))
                initiative_used += 1
        beats.sort(key=lambda beat: beat.priority, reverse=True)
        return beats[: budget.max_liveness_beats]


def _reaction_text(policy: BehaviorPolicy) -> str:
    body = "；".join(policy.body_language_guidance[:2]) or "动作短暂停顿"
    tactic = policy.preferred_tactics[0] if policy.preferred_tactics else "observe"
    return short_text(
        f"{policy.visible_expression}。可用肢体表现：{body}。当前倾向：{tactic}。",
        max_len=260,
    )


def _initiative_text(policy: BehaviorPolicy) -> str:
    if "move_private" in policy.preferred_tactics:
        return "如果玩家停顿或继续公开追问，该 NPC 倾向主动把谈话转到更私密的位置。"
    if "set_boundary" in policy.preferred_tactics:
        return "如果玩家继续施压，该 NPC 倾向先划清边界或发出警告，而不是立刻攻击。"
    if "ask_for_protection" in policy.preferred_tactics:
        return "如果玩家表现出善意，该 NPC 倾向先要求保护，再给出有限线索。"
    return "该 NPC 有轻微主动性，但本轮不应抢占玩家行动。"


def _priority(policy: BehaviorPolicy) -> float:
    return max(policy.deception_level, policy.aggression_level, policy.cooperation_level, 0.35)
