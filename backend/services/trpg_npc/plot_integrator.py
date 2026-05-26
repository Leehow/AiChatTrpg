"""Integrate resolved NPC actions into a SceneBeatPlan for the main narrative LLM."""
from __future__ import annotations

from .models import GameEvent, ResolveDecision, ResolvedAction, SceneBeat, SceneBeatPlan, SceneState


class PlotIntegrator:
    def build_scene_beat_plan(
        self,
        scene_state: SceneState,
        player_event: GameEvent,
        resolved_actions: list[ResolvedAction],
        scene_mood: str | None = None,
    ) -> SceneBeatPlan:
        must: list[SceneBeat] = []
        optional: list[SceneBeat] = []
        blocked: list[dict] = []

        for resolved in resolved_actions:
            proposal = resolved.proposal
            if resolved.decision == ResolveDecision.BLOCK:
                blocked.append({
                    "npc_id": proposal.actor_id,
                    "blocked_action": proposal.action_type.value,
                    "reason": resolved.reason,
                    "intent": proposal.intent,
                })
                continue

            beat_text = self._proposal_to_beat_text(resolved)
            beat = SceneBeat(
                type="NPC_REACTION" if proposal.consume_action_budget else "AMBIENT_REACTION",
                npc_id=proposal.actor_id,
                beat=beat_text,
                reason=resolved.reason,
                must_include=proposal.consume_action_budget,
                allowed_reveal_ids=proposal.reveal_fact_ids,
                forbidden_fact_ids=proposal.forbidden_fact_ids,
                source_action_id=proposal.source_card_id,
            )
            if beat.must_include:
                must.append(beat)
            else:
                optional.append(beat)

        tone_guidance = {
            "scene_mood": scene_mood or "根据当前场景保持节奏；NPC行动必须服务玩家当前输入。",
            "pacing": "每轮优先处理玩家动作，NPC行动只作为可裁定的剧情节拍进入叙述。",
        }
        if scene_state.plot_contract and scene_state.plot_contract.notes:
            tone_guidance["plot_notes"] = scene_state.plot_contract.notes

        return SceneBeatPlan(
            turn_id=scene_state.turn_id,
            scene_id=scene_state.scene_id,
            player_action_summary=player_event.content[:500],
            must_include_beats=must,
            optional_beats=optional,
            blocked_actions=blocked,
            tone_guidance=tone_guidance,
            action_budget=scene_state.action_budget,
            metadata={
                "plot_contract_goal": scene_state.plot_contract.scene_goal if scene_state.plot_contract else "",
                "source_event_id": player_event.event_id,
            },
        )

    def _proposal_to_beat_text(self, resolved: ResolvedAction) -> str:
        p = resolved.proposal
        pf = p.player_facing
        speech = pf.get("speech") or pf.get("speech_intent") or ""
        emote = pf.get("emote") or ""
        summary = p.gm_facing.get("decision_summary") or p.gm_facing.get("summary") or p.intent
        pieces = [str(x).strip() for x in [emote, speech, summary] if str(x).strip()]
        if resolved.decision == ResolveDecision.TRANSFORM:
            pieces.append("注意：这是经过裁定器降级/改写后的安全行动。")
        return " ".join(pieces)
