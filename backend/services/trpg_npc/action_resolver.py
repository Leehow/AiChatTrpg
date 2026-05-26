"""Validate/transform/block NPC action proposals before they enter narration."""
from __future__ import annotations

from copy import deepcopy

from .models import (
    ActionProposal,
    ActionType,
    NPCProfile,
    ResolveDecision,
    ResolvedAction,
    ScenePlotContract,
    SceneState,
)


class ActionResolver:
    def resolve(
        self,
        proposals: list[ActionProposal],
        scene_state: SceneState,
        profiles_by_id: dict[str, NPCProfile],
    ) -> list[ResolvedAction]:
        proposals = sorted(proposals, key=lambda p: p.priority, reverse=True)
        resolved: list[ResolvedAction] = []
        primary_used = 0
        clue_reveals_used = 0
        max_primary = scene_state.action_budget.get("max_primary_npc_actions", 1)
        max_clues = scene_state.action_budget.get(
            "max_clue_reveals_per_turn",
            scene_state.plot_contract.max_clue_reveals_per_turn if scene_state.plot_contract else 1,
        )

        for proposal in proposals:
            profile = profiles_by_id.get(proposal.actor_id)
            if profile is None:
                resolved.append(ResolvedAction(ResolveDecision.BLOCK, proposal, "Unknown NPC actor."))
                continue
            if proposal.actor_id not in scene_state.active_npc_ids and proposal.action_type != ActionType.OFFSCREEN:
                resolved.append(ResolvedAction(ResolveDecision.BLOCK, proposal, "NPC is not active in this scene."))
                continue
            if proposal.consume_action_budget and primary_used >= max_primary:
                resolved.append(ResolvedAction(ResolveDecision.BLOCK, proposal, "NPC primary action budget already used."))
                continue

            safe_action = self._guard_reveals(proposal, profile, scene_state.plot_contract)
            if safe_action is None:
                resolved.append(ResolvedAction(ResolveDecision.BLOCK, proposal, "Action would reveal forbidden/core facts."))
                continue
            if safe_action is not proposal:
                resolved.append(ResolvedAction(ResolveDecision.TRANSFORM, safe_action, "Forbidden reveal transformed into safe hint.", transformed_from=proposal))
                if safe_action.consume_action_budget:
                    primary_used += 1
                continue

            if proposal.action_type == ActionType.ATTACK:
                attack_resolution = self._resolve_attack(proposal, profile, scene_state.plot_contract)
                if attack_resolution.decision != ResolveDecision.ALLOW:
                    resolved.append(attack_resolution)
                    continue

            if proposal.reveal_fact_ids:
                if clue_reveals_used >= max_clues:
                    transformed = deepcopy(proposal)
                    transformed.action_type = ActionType.SAY
                    transformed.reveal_fact_ids = []
                    transformed.player_facing = {
                        "speech_intent": "避开完整线索，只留下一个模糊暗示。",
                        "emote": proposal.player_facing.get("emote", "NPC犹豫了一下，没有继续说下去。"),
                    }
                    resolved.append(ResolvedAction(ResolveDecision.TRANSFORM, transformed, "Clue reveal budget exceeded.", transformed_from=proposal))
                    if transformed.consume_action_budget:
                        primary_used += 1
                    continue
                clue_reveals_used += len(proposal.reveal_fact_ids)

            resolved.append(ResolvedAction(ResolveDecision.ALLOW, proposal, "Allowed."))
            if proposal.consume_action_budget:
                primary_used += 1
        return resolved

    def _guard_reveals(
        self,
        proposal: ActionProposal,
        profile: NPCProfile,
        plot_contract: ScenePlotContract | None,
    ) -> ActionProposal | None:
        forbidden = set(profile.plot_constraints.forbidden_fact_ids)
        forbidden.update(profile.plot_constraints.core_secret_ids if not profile.plot_constraints.can_reveal_core_secret else [])
        forbidden.update(proposal.forbidden_fact_ids)
        if plot_contract:
            forbidden.update(plot_contract.forbidden_reveals)

        accidental = set(proposal.reveal_fact_ids).intersection(forbidden)
        if not accidental:
            return proposal

        # Transform speech actions into safe hints. Hard world-changing reveals are blocked.
        if proposal.action_type in {ActionType.SAY, ActionType.REVEAL_CLUE, ActionType.DECEIVE, ActionType.DELAY}:
            transformed = deepcopy(proposal)
            transformed.action_type = ActionType.SAY
            transformed.reveal_fact_ids = [fid for fid in transformed.reveal_fact_ids if fid not in forbidden]
            transformed.player_facing = {
                "speech_intent": "给出不含核心秘密的模糊暗示或情绪反应。",
                "emote": proposal.player_facing.get("emote", "NPC明显意识到自己差点说漏嘴，立刻收住话头。"),
            }
            transformed.gm_facing["blocked_reveal_fact_ids"] = sorted(accidental)
            return transformed
        return None

    def _resolve_attack(
        self,
        proposal: ActionProposal,
        profile: NPCProfile,
        plot_contract: ScenePlotContract | None,
    ) -> ResolvedAction:
        mode = profile.plot_constraints.can_attack_players
        if mode == "always":
            return ResolvedAction(ResolveDecision.ALLOW, proposal, "Attack allowed by NPC constraints.")
        allowed_escalations = set(profile.plot_constraints.allowed_escalations)
        if plot_contract:
            allowed_escalations.update(plot_contract.allowed_escalations)
        if "npc_attack" in allowed_escalations or "combat" in allowed_escalations:
            return ResolvedAction(ResolveDecision.ALLOW, proposal, "Attack allowed by scene escalation.")

        transformed = deepcopy(proposal)
        transformed.action_type = ActionType.SAY
        transformed.player_facing = {
            "speech_intent": "升级为威胁或拔出武器，但给玩家反应机会，不直接造成伤害。",
            "emote": proposal.player_facing.get("emote", "NPC的手移向武器，但还没有真正动手。"),
        }
        transformed.mechanics = {"requires_check": False, "next_possible_state": "combat_if_players_push"}
        return ResolvedAction(ResolveDecision.TRANSFORM, transformed, "Attack transformed into threat; no attack trigger in plot contract.", transformed_from=proposal)
