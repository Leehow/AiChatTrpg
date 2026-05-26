"""Optional dedicated renderer when you do not want the main Scene Director to write dialogue."""
from __future__ import annotations

from .models import ActionProposal, BehaviorPolicy, VoiceCard


class DialogueRenderer:
    """Render a proposal into compact player-facing text.

    In the recommended architecture, Scene Director usually does final prose.
    This renderer is useful for direct NPC chat endpoints or tests.
    """

    def render(self, proposal: ActionProposal, voice_card: VoiceCard, behavior_policy: BehaviorPolicy | None = None) -> str:
        emote = proposal.player_facing.get("emote", "")
        speech = proposal.player_facing.get("speech", "")
        speech_intent = proposal.player_facing.get("speech_intent", "")
        if speech:
            line = speech
        elif speech_intent:
            line = f"（按意图表达：{speech_intent}）"
        else:
            line = "NPC没有明确开口，只通过姿态回应。"

        tone = voice_card.tone
        if behavior_policy:
            tone = f"{tone}; {behavior_policy.tone}"
        return "\n".join(x for x in [f"[{tone}] {emote}".strip(), line] if x.strip())
