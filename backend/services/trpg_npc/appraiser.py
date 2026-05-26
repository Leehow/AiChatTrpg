"""Rule-based event appraisal.

The appraiser translates raw scene events into psychologically meaningful
features. This is intentionally cheap enough for the foreground path.
"""
from __future__ import annotations

import re
from typing import Iterable

from .models import EventAppraisal, GameEvent, NPCProfile, NPCState, RelationshipVector
from .utils import clamp


class EventAppraiser:
    """Convert player/NPC/world events into an EventAppraisal vector."""

    THREAT_WORDS = ("杀", "打", "揍", "威胁", "枪", "刀", "attack", "kill", "hurt", "threat", "shoot")
    INSULT_WORDS = ("骗子", "蠢", "废物", "滚", "liar", "idiot", "trash", "coward")
    HELP_WORDS = ("帮助", "保护", "救", "治疗", "help", "protect", "save", "heal")
    OFFER_WORDS = ("给你", "报酬", "钱", "交易", "deal", "pay", "bribe", "reward")
    EVIDENCE_WORDS = ("证据", "符号", "地图", "信", "照片", "账本", "evidence", "symbol", "map", "letter", "photo")
    SECRET_WORDS = ("秘密", "邪教", "仪式", "失踪", "真相", "cult", "ritual", "secret", "missing", "truth")
    PUBLIC_WORDS = ("当众", "大厅", "人群", "公开", "public", "crowd", "hall", "everyone")

    TYPE_PRESETS: dict[str, EventAppraisal] = {
        "HELPED_NPC": EventAppraisal(help=0.8, protected=0.4),
        "PROTECTED_NPC": EventAppraisal(help=0.5, protected=0.9),
        "THREATENED_NPC": EventAppraisal(threat=0.8, physical_threat=0.4, insult=0.2),
        "INSULTED_NPC": EventAppraisal(insult=0.8, social_exposure=0.4),
        "ASKED_SENSITIVE_QUESTION": EventAppraisal(secret_exposure=0.6, uncertainty=0.4, goal_block=0.3),
        "REVEALED_EVIDENCE": EventAppraisal(evidence=0.8, uncertainty=0.3, secret_exposure=0.4),
        "OFFERED_DEAL": EventAppraisal(offer=0.8, uncertainty=0.2),
        "BROKE_PROMISE": EventAppraisal(betrayal=0.8, insult=0.2),
        "PUBLIC_EXPOSURE": EventAppraisal(social_exposure=0.9, secret_exposure=0.6, public_pressure=0.8),
        "PHYSICAL_ATTACK": EventAppraisal(threat=1.0, physical_threat=1.0, insult=0.4),
        "NPC_ATTACKED": EventAppraisal(threat=1.0, physical_threat=1.0),
        "PLAYER_INPUT": EventAppraisal(uncertainty=0.1),
    }

    def appraise(
        self,
        event: GameEvent,
        npc_profile: NPCProfile | None = None,
        npc_state: NPCState | None = None,
        relationship: RelationshipVector | None = None,
        scene_tags: Iterable[str] | None = None,
    ) -> EventAppraisal:
        preset = self.TYPE_PRESETS.get(event.type, EventAppraisal())
        out = EventAppraisal(**preset.to_dict())
        text = f"{event.content} {' '.join(str(v) for v in event.payload.values())}".lower()

        self._add_keyword_signal(out, text)
        self._add_scene_signal(out, scene_tags or [])
        self._add_relationship_signal(out, relationship)
        self._add_profile_signal(out, npc_profile)
        self._normalize(out)
        return out

    def _add_keyword_signal(self, out: EventAppraisal, text: str) -> None:
        if self._contains(text, self.THREAT_WORDS):
            out.threat += 0.45
            out.physical_threat += 0.35
        if self._contains(text, self.INSULT_WORDS):
            out.insult += 0.55
        if self._contains(text, self.HELP_WORDS):
            out.help += 0.45
            out.protected += 0.25
        if self._contains(text, self.OFFER_WORDS):
            out.offer += 0.45
            out.uncertainty += 0.10
        if self._contains(text, self.EVIDENCE_WORDS):
            out.evidence += 0.50
            out.uncertainty += 0.15
        if self._contains(text, self.SECRET_WORDS):
            out.secret_exposure += 0.55
            out.goal_block += 0.20
        if self._contains(text, self.PUBLIC_WORDS):
            out.social_exposure += 0.45
            out.public_pressure += 0.45

    def _add_scene_signal(self, out: EventAppraisal, scene_tags: Iterable[str]) -> None:
        tags = set(scene_tags)
        if "public" in tags:
            out.social_exposure += 0.25
            out.public_pressure += 0.25
        if "combat" in tags:
            out.physical_threat += 0.20
            out.threat += 0.20
        if "private" in tags:
            out.social_exposure *= 0.50
            out.public_pressure *= 0.50

    def _add_relationship_signal(self, out: EventAppraisal, relationship: RelationshipVector | None) -> None:
        if relationship is None:
            return
        # Existing distrust makes ambiguous events feel more suspicious.
        out.uncertainty += relationship.suspicion * 0.15
        out.threat += relationship.fear * 0.10
        # Existing trust softens mild uncertainty.
        out.uncertainty -= relationship.trust * 0.08

    def _add_profile_signal(self, out: EventAppraisal, npc_profile: NPCProfile | None) -> None:
        if npc_profile is None:
            return
        if npc_profile.plot_constraints.core_secret_ids:
            # Characters holding major secrets appraise sensitive questions harder.
            out.secret_exposure += out.uncertainty * 0.10

    def _normalize(self, out: EventAppraisal) -> None:
        for name in out.__dataclass_fields__:
            setattr(out, name, clamp(getattr(out, name)))

    @staticmethod
    def _contains(text: str, words: Iterable[str]) -> bool:
        return any(w.lower() in text for w in words) or bool(
            re.search(r"\b(accuse|threaten|bribe|attack|protect|save)\b", text)
        )
