"""Compile numeric state vectors into LLM-friendly behavior policy."""
from __future__ import annotations

from .models import BehaviorPolicy, NPCMode, NPCProfile, NPCState, RelationshipVector
from .utils import clamp


class BehaviorPolicyCompiler:
    """Turn mood + relationship + mode into a compact performance/action policy."""

    def compile(
        self,
        profile: NPCProfile,
        state: NPCState,
        relationships: dict[str, RelationshipVector] | None = None,
        target_id: str | None = None,
    ) -> BehaviorPolicy:
        relationships = relationships or {}
        rel = relationships.get(target_id or "", RelationshipVector())
        mood = state.mood.normalized()
        mode = self._mode(profile, state.current_mode)

        dominant = self._dominant_mood(mood)
        visible = self._visible_expression(profile, state, mode, dominant)
        cooperation = clamp(0.45 + rel.trust * 0.35 + rel.debt * 0.10 - rel.suspicion * 0.25 - mood.suspicion * 0.20 - mood.fear * 0.10)
        deception = clamp(profile.persona.deception_skill * 0.45 + mood.suspicion * 0.30 + state.goal_pressure.get("protect_secret", 0.0) * 0.35)
        aggression = clamp(mood.anger * 0.45 + profile.persona.dominance * 0.25 - profile.persona.impulse_control * 0.20 + rel.resentment * 0.20)
        risk = clamp(0.45 + profile.persona.dominance * 0.15 + profile.persona.fanaticism * 0.20 - mood.fear * 0.25 - state.goal_pressure.get("survive", 0.0) * 0.20)

        if mode:
            cooperation = clamp(cooperation + mode.policy_bias.get("cooperation_level", 0.0))
            deception = clamp(deception + mode.policy_bias.get("deception_level", 0.0))
            aggression = clamp(aggression + mode.policy_bias.get("aggression_level", 0.0))
            risk = clamp(risk + mode.policy_bias.get("risk_tolerance", 0.0))

        tone = self._tone(profile, mode, dominant, visible)
        speech_style = self._speech_style(dominant, deception, aggression, cooperation)
        forbidden = list(profile.voice_card.forbidden_style)
        if not profile.plot_constraints.can_reveal_core_secret:
            forbidden.append("do_not_reveal_core_secret")
        if profile.plot_constraints.can_attack_players != "always":
            forbidden.append("do_not_attack_without_trigger")
        forbidden.append("do_not_explain_inner_state_directly")

        return BehaviorPolicy(
            dominant_mood=dominant,
            inner_state={
                "fear": round(mood.fear, 3),
                "anger": round(mood.anger, 3),
                "suspicion": round(mood.suspicion, 3),
                "curiosity": round(mood.curiosity, 3),
                "stress": round(mood.stress, 3),
            },
            visible_expression=visible,
            tone=tone,
            speech_style=speech_style,
            cooperation_level=round(cooperation, 3),
            deception_level=round(deception, 3),
            aggression_level=round(aggression, 3),
            risk_tolerance=round(risk, 3),
            forbidden_behaviors=forbidden,
            strategy_summary=self._strategy_summary(dominant, cooperation, deception, aggression, risk),
        )

    def _mode(self, profile: NPCProfile, mode_id: str) -> NPCMode | None:
        for mode in profile.modes:
            if mode.mode_id == mode_id:
                return mode
        return profile.modes[0] if profile.modes else None

    def _dominant_mood(self, mood) -> str:
        if mood.suspicion >= 0.65 and mood.fear >= 0.45:
            return "controlled_suspicion"
        if mood.fear >= 0.75:
            return "afraid"
        if mood.anger >= 0.70 and mood.dominance_feeling >= 0.45:
            return "confrontational"
        if mood.stress >= 0.75:
            return "stressed"
        if mood.curiosity >= 0.70 and mood.suspicion >= 0.45:
            return "probing"
        if mood.valence > 0.35 and mood.joy > 0.35:
            return "warm"
        return "neutral"

    def _visible_expression(self, profile: NPCProfile, state: NPCState, mode: NPCMode | None, dominant: str) -> str:
        if mode and mode.visible_expression:
            return mode.visible_expression
        p = profile.persona
        if p.deception_skill > 0.65 and p.impulse_control > 0.55 and state.mood.stress > 0.45:
            return "polite_but_guarded"
        if dominant == "afraid" and p.impulse_control < 0.35:
            return "visibly_frightened"
        if dominant == "confrontational":
            return "coldly_hostile" if p.impulse_control > 0.55 else "openly_angry"
        if dominant == "probing":
            return "attentive_and_questioning"
        return "neutral"

    def _tone(self, profile: NPCProfile, mode: NPCMode | None, dominant: str, visible: str) -> str:
        parts = [profile.voice_card.tone]
        if mode and mode.tone_bias:
            parts.append(mode.tone_bias)
        if visible == "polite_but_guarded":
            parts.append("restrained, evasive")
        elif dominant == "afraid":
            parts.append("low, urgent")
        elif dominant == "confrontational":
            parts.append("sharp, controlled")
        elif dominant == "probing":
            parts.append("curious, precise")
        return "; ".join(p for p in parts if p)

    def _speech_style(self, dominant: str, deception: float, aggression: float, cooperation: float) -> list[str]:
        style: list[str] = []
        if deception > 0.60:
            style.extend(["partial truths", "redirects", "avoid specific names and locations"])
        if aggression > 0.60:
            style.extend(["short commands", "interrupts", "threatening subtext"])
        if cooperation < 0.35:
            style.extend(["short answers", "asks probing questions"])
        if dominant == "afraid":
            style.extend(["lower voice", "watch exits", "request reassurance or protection"])
        if not style:
            style = ["natural conversation", "respond to the immediate situation"]
        return list(dict.fromkeys(style))

    def _strategy_summary(self, dominant: str, cooperation: float, deception: float, aggression: float, risk: float) -> str:
        if deception > 0.65 and cooperation < 0.40:
            return "Probe what the players know, give only safe partial information, and protect secrets."
        if cooperation > 0.65:
            return "Help the players within plot constraints, but do not over-explain hidden truths."
        if aggression > 0.65:
            return "Pressure or warn the players before escalating to rules-mediated conflict."
        if risk < 0.30:
            return "Avoid commitment, seek safety, and delay direct confrontation."
        return f"Maintain a {dominant} posture while pursuing the current goal."
