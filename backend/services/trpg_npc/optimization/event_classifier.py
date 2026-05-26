"""Lightweight pre-turn event classifier for NPC Runtime V2.

ActionBoard matching should be based primarily on structured events, not raw
keyword matching.  This module provides a deterministic fallback classifier for
Chinese/English player text.  It is deliberately simple and fast enough to run
in the foreground before the main scene LLM call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .common import first_non_empty, get_value, stable_list
from .safe_projection import prompt_safe_active_npcs_hardened


@dataclass(slots=True)
class ClassifiedEvent:
    event_id: str
    type: str
    scene_id: str
    turn_id: int
    actor_id: str = "pc"
    target_ids: list[str] = field(default_factory=list)
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, bool] = field(
        default_factory=lambda: {"player_visible": True, "gm_visible": True}
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "scene_id": self.scene_id,
            "turn_id": self.turn_id,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "content": self.content,
            "payload": dict(self.payload),
            "visibility": dict(self.visibility),
        }


@dataclass(frozen=True, slots=True)
class PatternRule:
    event_type: str
    patterns: tuple[str, ...]
    tags: tuple[str, ...] = ()
    confidence: float = 0.7


RULES: tuple[PatternRule, ...] = (
    PatternRule(
        "ASKED_SENSITIVE_QUESTION",
        (
            r"邪教|仪式|主谋|幕后|秘密|账本|失踪|符号|徽记|图案|转化室|祭司|神庙",
            r"cult|ritual|secret|ledger|missing|symbol|sigil|temple|priestess|conspiracy",
        ),
        ("sensitive_question", "secret_topic"),
        0.75,
    ),
    PatternRule(
        "DISPLAYED_EVIDENCE",
        (
            r"展示|拿出|递给|给.*看|画给|摊开|出示|证据|照片|徽记|符号|图案",
            r"show|display|present|draw|evidence|photo|symbol|sigil",
        ),
        ("evidence",),
        0.78,
    ),
    PatternRule(
        "THREATENED_NPC",
        (
            r"威胁|恐吓|逼问|拔枪|拔刀|拿枪|拿刀|不说.*就|再不说|按住|抓住",
            r"threaten|intimidate|draw.*gun|draw.*knife|force|grab|corner",
        ),
        ("threat",),
        0.82,
    ),
    PatternRule(
        "ATTACKED_NPC",
        (
            r"攻击|开枪|射击|砍|刺|打他|打她|打店主|挥剑|施法攻击|杀",
            r"attack|shoot|stab|slash|punch|kill|cast.*at",
        ),
        ("attack",),
        0.88,
    ),
    PatternRule(
        "OFFERED_DEAL",
        (
            r"交易|条件|交换|给钱|金币|买通|贿赂|报酬|好处|帮你.*你帮我",
            r"deal|bargain|bribe|pay|gold|reward|trade|offer",
        ),
        ("deal",),
        0.72,
    ),
    PatternRule(
        "OFFERED_PROTECTION",
        (
            r"保护你|保证.*安全|帮你|救你|不用怕|我们会保护|带你离开",
            r"protect|keep.*safe|help you|save you|escort",
        ),
        ("protection", "help"),
        0.76,
    ),
    PatternRule(
        "PLAYER_ATTEMPTED_TO_LEAVE",
        (
            r"离开|走出|退出|转身走|去下一个|前往|出门|上路|离场",
            r"leave|exit|walk out|go to|depart|move on",
        ),
        ("leave_scene",),
        0.7,
    ),
    PatternRule(
        "PUBLIC_EXPOSURE",
        (
            r"大声|当众|公开|喊出来|让所有人|对大家说|在大厅里说",
            r"loudly|publicly|in front of everyone|announce|shout",
        ),
        ("public", "exposure"),
        0.74,
    ),
    PatternRule(
        "DIRECT_NPC_DIALOGUE",
        (
            r"我问|我对.*说|询问|追问|搭话|交谈|压低声音问|试探",
            r"ask|talk to|speak to|question|press|probe",
        ),
        ("dialogue",),
        0.68,
    ),
)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _regex_hit(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _npc_aliases(npc: Any) -> list[str]:
    aliases: list[str] = []
    for key in ["key", "npc_id", "id", "player_known_name", "display_name", "public_name", "name", "role"]:
        value = get_value(npc, key)
        if value and isinstance(value, str):
            aliases.append(value)
    return sorted(set(a for a in aliases if len(a.strip()) >= 2), key=len, reverse=True)


def _detect_targets(text: str, active_npcs: list[Any]) -> list[str]:
    targets: list[str] = []
    for npc in active_npcs or []:
        npc_id = first_non_empty(get_value(npc, "key"), get_value(npc, "npc_id"), get_value(npc, "id"))
        if not npc_id:
            continue
        for alias in _npc_aliases(npc):
            if alias and alias in text:
                targets.append(str(npc_id))
                break
    if not targets and len(active_npcs or []) == 1:
        npc = active_npcs[0]
        npc_id = first_non_empty(get_value(npc, "key"), get_value(npc, "npc_id"), get_value(npc, "id"))
        if npc_id:
            # Single active NPC scenes often omit the NPC name: “我继续追问”.
            targets.append(str(npc_id))
    return sorted(set(targets))


def _topic_tags(text: str) -> list[str]:
    tags: set[str] = set()
    tag_patterns = {
        "cult": r"邪教|教团|cult",
        "ritual": r"仪式|ritual",
        "symbol": r"符号|徽记|图案|symbol|sigil",
        "missing_person": r"失踪|missing",
        "ledger": r"账本|ledger",
        "temple": r"神庙|temple",
        "serpent": r"蛇人|蛇|serpent",
        "identity": r"身份|主谋|幕后|leader|identity",
    }
    for tag, pattern in tag_patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            tags.add(tag)
    return sorted(tags)


def classify_player_text_to_events(
    player_text: str,
    active_npcs: list[Any] | None,
    *,
    scene_id: str,
    turn_id: int,
    actor_id: str = "pc",
    include_safe_npc_projection: bool = False,
) -> list[dict[str, Any]]:
    """Classify player text into deterministic pre-turn ``GameEvent`` dicts.

    The classifier is meant to be fast and conservative.  It can be replaced by
    a small model later, but the output contract should stay the same.
    """

    text = _normalize_text(player_text)
    if not text:
        return []

    targets = _detect_targets(text, active_npcs or [])
    topics = _topic_tags(text)
    events: list[ClassifiedEvent] = []

    for idx, rule in enumerate(RULES):
        if not _regex_hit(rule.patterns, text):
            continue
        payload: dict[str, Any] = {
            "confidence": rule.confidence,
            "topic_tags": sorted(set(rule.tags).union(topics)),
            "detector": "deterministic_pre_turn_v1",
        }
        if include_safe_npc_projection and active_npcs:
            payload["active_npcs"] = prompt_safe_active_npcs_hardened(active_npcs)
        events.append(
            ClassifiedEvent(
                event_id=f"turn_{turn_id}_{idx}_{rule.event_type.lower()}",
                type=rule.event_type,
                scene_id=scene_id,
                turn_id=turn_id,
                actor_id=actor_id,
                target_ids=targets,
                content=text[:1200],
                payload=payload,
            )
        )

    # If the text mentions an NPC but no rule fired, still produce a low-cost
    # direct interaction event so the ActionBoard can consider “addressed NPC” cards.
    if not events and targets:
        events.append(
            ClassifiedEvent(
                event_id=f"turn_{turn_id}_direct_npc_reference",
                type="DIRECT_NPC_REFERENCE",
                scene_id=scene_id,
                turn_id=turn_id,
                actor_id=actor_id,
                target_ids=targets,
                content=text[:1200],
                payload={
                    "confidence": 0.55,
                    "topic_tags": topics,
                    "detector": "deterministic_pre_turn_v1",
                },
            )
        )

    return [event.to_dict() for event in events]


STRING_TRIGGER_TO_EVENT_TYPES: dict[str, set[str]] = {
    "player_targets_npc": {
        "DIRECT_NPC_DIALOGUE",
        "DIRECT_NPC_REFERENCE",
        "ASKED_SENSITIVE_QUESTION",
        "DISPLAYED_EVIDENCE",
        "THREATENED_NPC",
        "ATTACKED_NPC",
        "OFFERED_DEAL",
        "OFFERED_PROTECTION",
        "PLAYER_ATTEMPTED_TO_LEAVE",
        "PUBLIC_EXPOSURE",
    },
    "player_asks_sensitive_question": {"ASKED_SENSITIVE_QUESTION"},
    "player_mentions_secret": {"ASKED_SENSITIVE_QUESTION"},
    "player_mentions_cult_symbol": {"ASKED_SENSITIVE_QUESTION", "DISPLAYED_EVIDENCE"},
    "player_reveals_evidence": {"DISPLAYED_EVIDENCE"},
    "player_mentions_symbol": {"ASKED_SENSITIVE_QUESTION", "DISPLAYED_EVIDENCE"},
    "player_shows_evidence": {"DISPLAYED_EVIDENCE"},
    "player_is_aggressive": {"THREATENED_NPC", "ATTACKED_NPC"},
    "player_threatens": {"THREATENED_NPC"},
    "physical_threat": {"THREATENED_NPC", "ATTACKED_NPC"},
    "player_attacks": {"ATTACKED_NPC"},
    "player_offers_deal": {"OFFERED_DEAL"},
    "player_offers_protection": {"OFFERED_PROTECTION"},
    "player_attempts_to_leave": {"PLAYER_ATTEMPTED_TO_LEAVE"},
    "public_exposure": {"PUBLIC_EXPOSURE"},
    "direct_dialogue": {"DIRECT_NPC_DIALOGUE", "DIRECT_NPC_REFERENCE"},
}
