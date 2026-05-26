"""Compile internal state into visible expression masks."""

from __future__ import annotations

from typing import Any

from .common import clamp, get_value, text_blob
from .models import ExpressionMask, LivenessCard


class ExpressionMaskEngine:
    def compile(self, *, profile: Any, state: Any, liveness: LivenessCard, relationship: Any | None = None) -> ExpressionMask:
        npc_id = str(get_value(profile, "npc_id") or get_value(state, "npc_id") or liveness.npc_id)
        mood = get_value(state, "mood") or {}
        persona = get_value(profile, "persona") or {}
        fear = _num(mood, "fear")
        anger = _num(mood, "anger")
        suspicion = _num(mood, "suspicion")
        stress = _num(mood, "stress")
        curiosity = _num(mood, "curiosity")
        impulse_control = _num(persona, "impulse_control", default=0.5)
        dominance = _num(persona, "dominance", default=0.4)
        deception = _num(persona, "deception_skill", default=0.3)
        trust = _num(relationship, "trust", default=0.3)
        blob = text_blob(profile, liveness.default_stance)

        if fear > 0.72 and impulse_control < 0.45:
            return ExpressionMask(
                npc_id=npc_id,
                mask_id="visible_panic",
                hidden_state_label="fear_spike",
                visible_expression="慌乱、急促、难以维持完整解释",
                social_mask="mask_breaking",
                body_language=_pick(liveness.physical_tells, ["后退半步", "不断确认出口"]),
                voice_guidance={"sentence_length": "short", "directness": "low", "pace": "fast"},
            )
        if fear > 0.65 and deception > 0.55:
            return ExpressionMask(
                npc_id=npc_id,
                mask_id="controlled_evasion",
                hidden_state_label="controlled_fear",
                visible_expression="表面镇定但明显回避关键点",
                social_mask="polite_evasion",
                body_language=_pick(liveness.physical_tells, ["把注意力转向手边物件", "短暂看向门口"]),
                voice_guidance={"sentence_length": "short", "directness": "low", "question_ratio": "high"},
            )
        if anger > 0.6 and dominance > 0.55:
            return ExpressionMask(
                npc_id=npc_id,
                mask_id="cold_intimidation",
                hidden_state_label="controlled_anger",
                visible_expression="压住怒意，用冷淡和边界感回应",
                social_mask="dominance_mask",
                body_language=_pick(liveness.physical_tells, ["动作变慢", "目光固定在玩家身上"]),
                voice_guidance={"sentence_length": "medium", "directness": "high", "pace": "slow"},
            )
        if suspicion > 0.7 or stress > 0.7:
            return ExpressionMask(
                npc_id=npc_id,
                mask_id="polite_but_guarded",
                hidden_state_label="suspicion_or_stress",
                visible_expression="礼貌但防备，不愿在公开场合展开",
                social_mask="guarded_civility",
                body_language=_pick(liveness.physical_tells, ["避开视线", "手上动作停顿一瞬"]),
                voice_guidance={"sentence_length": "short", "directness": "medium_low", "question_ratio": "medium"},
            )
        if curiosity > 0.55 and trust > 0.45:
            return ExpressionMask(
                npc_id=npc_id,
                mask_id="cautious_interest",
                hidden_state_label="curiosity",
                visible_expression="谨慎但愿意继续听下去",
                social_mask="measured_openness",
                body_language=_pick(liveness.physical_tells, ["身体略微前倾", "停下手头动作"]),
                voice_guidance={"sentence_length": "medium", "directness": "medium", "question_ratio": "medium_high"},
            )
        return ExpressionMask(
            npc_id=npc_id,
            mask_id="surface_neutral",
            hidden_state_label="baseline",
            visible_expression="保持表面常态，只露出轻微情绪痕迹",
            social_mask=liveness.default_stance,
            body_language=_pick(liveness.physical_tells, ["视线短暂停留在玩家身上"]),
            voice_guidance={"sentence_length": "medium", "directness": "medium", "question_ratio": "low"},
        )


def _num(obj: Any, key: str, default: float = 0.0) -> float:
    return clamp(get_value(obj, key, default), default=default)


def _pick(values: list[str], fallback: list[str], limit: int = 2) -> list[str]:
    out = [str(v) for v in values if str(v).strip()]
    return (out or fallback)[:limit]
