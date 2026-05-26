"""Card-build pipeline for the background NPC planner.

Holds the diagnostics dataclasses, the JSON-to-card translation, the secret
guard pass, the memory-leak audit, and the trigger normalisation helpers that
used to live alongside the planner facade.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from services.trpg_memory.memory_models import MemoryItem
from services.trpg_npc.background_planner_constants import (
    _ALLOWED_STRUCTURED_EVENT_TYPES,
    _ALLOWED_TOPIC_TAGS,
    _ALLOWED_TRIGGERS,
)
from services.trpg_npc.background_planner_utils import (
    _action_type,
    _float,
    _int,
    _list_strings,
    _parse_json,
    _short_text,
)
from services.trpg_npc.knowledge_runtime import leak_warnings_to_dict
from services.trpg_npc.leak_checker import LeakChecker, LeakWarning
from services.trpg_npc.models import (
    ActionProposal,
    NPCIntentCard,
    NPCProfile,
)
from services.trpg_npc.optimization.secret_guard import ForbiddenContentGuard, ForbiddenFact
from services.trpg_npc.utils import clamp, new_id


logger = logging.getLogger("chatrpg.trpg_npc.background_planner")


@dataclass(slots=True)
class PlannerCardBuildDiagnostics:
    raw_card_count: int = 0
    accepted_card_count: int = 0
    invalid_card_count: int = 0
    unknown_npc_count: int = 0
    duplicate_npc_count: int = 0
    structured_trigger_count: int = 0
    legacy_trigger_count: int = 0
    default_triggered_card_count: int = 0
    secret_guard_transformed: int = 0
    secret_guard_blocked: int = 0
    knowledge_leak_warning_count: int = 0
    knowledge_leak_blocked: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "raw_card_count": self.raw_card_count,
            "accepted_card_count": self.accepted_card_count,
            "invalid_card_count": self.invalid_card_count,
            "unknown_npc_count": self.unknown_npc_count,
            "duplicate_npc_count": self.duplicate_npc_count,
            "structured_trigger_count": self.structured_trigger_count,
            "legacy_trigger_count": self.legacy_trigger_count,
            "default_triggered_card_count": self.default_triggered_card_count,
            "secret_guard_transformed": self.secret_guard_transformed,
            "secret_guard_blocked": self.secret_guard_blocked,
            "knowledge_leak_warning_count": self.knowledge_leak_warning_count,
            "knowledge_leak_blocked": self.knowledge_leak_blocked,
        }


@dataclass(slots=True)
class PlannerCardBuildResult:
    cards: list[NPCIntentCard]
    diagnostics: PlannerCardBuildDiagnostics


def build_cards_from_planner_response(
    raw: str,
    *,
    profiles_by_id: dict[str, NPCProfile],
    based_on_turn_id: int,
    forbidden_memories_by_npc_id: dict[str, Any] | None = None,
) -> list[NPCIntentCard]:
    return build_cards_from_planner_response_detailed(
        raw,
        profiles_by_id=profiles_by_id,
        based_on_turn_id=based_on_turn_id,
        forbidden_memories_by_npc_id=forbidden_memories_by_npc_id,
    ).cards


def build_cards_from_planner_response_detailed(
    raw: str,
    *,
    profiles_by_id: dict[str, NPCProfile],
    based_on_turn_id: int,
    forbidden_memories_by_npc_id: dict[str, Any] | None = None,
) -> PlannerCardBuildResult:
    data = _parse_json(raw)
    raw_cards: Any = data.get("cards") if isinstance(data, dict) else data
    if not isinstance(raw_cards, list):
        diagnostics = PlannerCardBuildDiagnostics(invalid_card_count=1 if raw else 0)
        return PlannerCardBuildResult(cards=[], diagnostics=diagnostics)

    cards: list[NPCIntentCard] = []
    diagnostics = PlannerCardBuildDiagnostics(raw_card_count=len(raw_cards))
    seen_npcs: set[str] = set()
    forbidden_by_npc = forbidden_memories_by_npc_id or {}
    for item in raw_cards:
        if not isinstance(item, dict):
            diagnostics.invalid_card_count += 1
            continue
        npc_id = str(item.get("npc_id") or "").strip()
        profile = profiles_by_id.get(npc_id)
        if not npc_id or profile is None:
            diagnostics.unknown_npc_count += 1
            continue
        if npc_id in seen_npcs:
            diagnostics.duplicate_npc_count += 1
            continue
        card = _card_from_dict(item, profile=profile, based_on_turn_id=based_on_turn_id)
        if card is None:
            diagnostics.invalid_card_count += 1
            continue
        _add_trigger_diagnostics(diagnostics, card)
        guarded_card = _guard_planner_card_secrets(card, profile)
        guard = card.metadata.get("secret_guard") if isinstance(card.metadata, dict) else None
        if isinstance(guard, dict) and guard.get("decision") == "transform":
            diagnostics.secret_guard_transformed += 1
        if guarded_card is None:
            diagnostics.secret_guard_blocked += 1
            continue
        card = guarded_card
        leaks = _audit_card_memory_leaks(
            card,
            forbidden_by_npc.get(profile.npc_id) or (),
        )
        if leaks:
            diagnostics.knowledge_leak_warning_count += len(leaks)
            diagnostics.knowledge_leak_blocked += 1
            logger.info(
                "[npc_background_planner] blocked memory-leaking planner card npc_id=%s memory_ids=%s",
                profile.npc_id,
                [warning.memory_id for warning in leaks],
            )
            continue
        if card is not None:
            seen_npcs.add(npc_id)
            cards.append(card)
            diagnostics.accepted_card_count += 1
    return PlannerCardBuildResult(cards=cards, diagnostics=diagnostics)


def _card_from_dict(
    raw: dict[str, Any],
    *,
    profile: NPCProfile,
    based_on_turn_id: int,
) -> NPCIntentCard | None:
    action_type = _action_type(raw.get("action_type"))
    priority = clamp(_float(raw.get("priority"), default=0.62))
    forbidden_fact_ids = list(dict.fromkeys(
        profile.plot_constraints.forbidden_fact_ids
        + profile.plot_constraints.core_secret_ids
        + _list_strings(raw.get("forbidden_fact_ids"))
    ))
    known_fact_ids = _known_fact_ids(raw, profile)
    proposal = ActionProposal(
        actor_id=profile.npc_id,
        intent=_short_text(raw.get("intent"), fallback="respond_to_player", max_len=120),
        action_type=action_type,
        target_ids=_list_strings(raw.get("target_ids")) or ["pc"],
        priority=priority,
        player_facing={
            "speech_intent": _short_text(raw.get("speech_intent"), max_len=260),
            "emote": _short_text(raw.get("emote"), max_len=180),
        },
        gm_facing={
            "decision_summary": _short_text(raw.get("gm_notes"), max_len=260),
            "planner": "llm_background",
        },
        known_fact_ids=known_fact_ids,
        forbidden_fact_ids=forbidden_fact_ids,
    )
    valid_for_turns = max(1, min(4, _int(raw.get("valid_for_turns"), default=2)))
    triggers = _trigger_conditions_from_raw(raw.get("trigger_conditions"))
    trigger_source = "planner"
    if not triggers:
        triggers = _default_structured_triggers()
        trigger_source = "default"
    return NPCIntentCard(
        card_id=new_id("intent"),
        npc_id=profile.npc_id,
        based_on_turn_id=int(based_on_turn_id or 0),
        valid_until_turn=int(based_on_turn_id or 0) + valid_for_turns,
        priority=priority,
        trigger_conditions=triggers,
        preferred_action=proposal,
        motivation=_short_text(raw.get("motivation"), max_len=240),
        known_fact_ids=known_fact_ids,
        forbidden_fact_ids=forbidden_fact_ids,
        plot_constraints=profile.plot_constraints,
        metadata={
            "planner": "llm_background",
            "trigger_source": trigger_source,
            "trigger_stats": _trigger_stats(triggers),
        },
    )


def _guard_planner_card_secrets(card: NPCIntentCard, profile: NPCProfile) -> NPCIntentCard | None:
    guard = ForbiddenContentGuard(_forbidden_facts_for_profile(profile, card.forbidden_fact_ids))
    proposal = card.preferred_action
    payload = {
        "action_type": proposal.action_type.value,
        "intent": proposal.intent,
        "speech_intent": proposal.player_facing.get("speech_intent", ""),
        "emote": proposal.player_facing.get("emote", ""),
        "gm_notes": proposal.gm_facing.get("decision_summary", ""),
        "motivation": card.motivation,
    }
    decision = guard.sanitize_action(payload)
    if decision.decision == "allow":
        return card

    guard_summary = {
        "decision": decision.decision,
        "blocked_fact_ids": sorted({violation.fact_id for violation in decision.violations}),
        "violation_count": len(decision.violations),
    }
    card.metadata["secret_guard"] = guard_summary
    proposal.gm_facing["secret_guard"] = guard_summary
    if decision.decision == "block":
        logger.info(
            "[npc_background_planner] blocked unsafe planner card npc_id=%s fact_ids=%s",
            profile.npc_id,
            guard_summary["blocked_fact_ids"],
        )
        return None

    sanitized = decision.action if isinstance(decision.action, dict) else {}
    proposal.intent = _short_text(sanitized.get("intent"), fallback=proposal.intent, max_len=120)
    proposal.player_facing["speech_intent"] = _short_text(
        sanitized.get("speech_intent"),
        fallback="给出模糊回应，避免直接说出受保护秘密。",
        max_len=260,
    )
    proposal.player_facing["emote"] = _short_text(
        sanitized.get("emote"),
        fallback=proposal.player_facing.get("emote", ""),
        max_len=180,
    )
    proposal.gm_facing["decision_summary"] = _short_text(
        sanitized.get("gm_notes"),
        fallback="Secret guard transformed this planner card into a vague hint.",
        max_len=260,
    )
    card.motivation = _short_text(
        sanitized.get("motivation"),
        fallback="Avoid revealing protected facts while preserving NPC intent.",
        max_len=240,
    )
    return card


def _audit_card_memory_leaks(
    card: NPCIntentCard,
    forbidden_memories: Any,
) -> tuple[LeakWarning, ...]:
    memories = tuple(
        memory for memory in (forbidden_memories or ())
        if isinstance(memory, MemoryItem)
    )
    if not memories:
        return ()
    proposal = card.preferred_action
    generated_text = "\n".join(
        str(part or "")
        for part in (
            proposal.intent,
            proposal.player_facing.get("speech_intent", ""),
            proposal.player_facing.get("emote", ""),
            proposal.gm_facing.get("decision_summary", ""),
            card.motivation,
        )
    )
    warnings = LeakChecker().check(
        generated_text=generated_text,
        forbidden_memories=memories,
    )
    if warnings:
        proposal.gm_facing["knowledge_leak_warnings"] = leak_warnings_to_dict(warnings)
        card.metadata["knowledge_leak_warnings"] = leak_warnings_to_dict(warnings)
    return warnings


def _trigger_conditions_from_raw(value: Any) -> list[Any]:
    raw_items = value if isinstance(value, list) else [value]
    triggers: list[Any] = []
    for item in raw_items:
        if isinstance(item, dict):
            trigger = _structured_trigger_from_dict(item)
            if trigger:
                triggers.append(trigger)
            continue
        if isinstance(item, str):
            trigger = item.strip()
            if trigger in _ALLOWED_TRIGGERS:
                triggers.append(trigger)
    return triggers


def _structured_trigger_from_dict(raw: dict[str, Any]) -> dict[str, Any]:
    event_type = str(raw.get("event_type") or "").strip().upper()
    event_types = [
        event.strip().upper()
        for event in _list_strings(raw.get("event_types"))
        if event.strip().upper() in _ALLOWED_STRUCTURED_EVENT_TYPES
    ]
    if event_type in _ALLOWED_STRUCTURED_EVENT_TYPES:
        trigger: dict[str, Any] = {"event_type": event_type}
    elif event_types:
        trigger = {"event_types": event_types[:3]}
    else:
        return {}

    topic_tags = [
        tag for tag in _list_strings(raw.get("topic_tags"))
        if tag in _ALLOWED_TOPIC_TAGS
    ]
    if topic_tags:
        trigger["topic_tags"] = topic_tags[:4]

    target_ids = _list_strings(raw.get("target_ids"))
    if target_ids:
        trigger["target_ids"] = target_ids[:4]

    if "require_target" in raw:
        trigger["require_target"] = bool(raw.get("require_target"))

    if "min_confidence" in raw:
        trigger["min_confidence"] = round(clamp(_float(raw.get("min_confidence"), default=0.0)), 2)

    return trigger


def _default_structured_triggers() -> list[dict[str, Any]]:
    return [
        {"event_type": "DIRECT_NPC_DIALOGUE", "require_target": True, "min_confidence": 0.55},
        {"event_type": "ASKED_SENSITIVE_QUESTION", "min_confidence": 0.6},
    ]


def _trigger_stats(triggers: list[Any]) -> dict[str, int]:
    return {
        "structured": sum(1 for trigger in triggers if isinstance(trigger, dict)),
        "legacy": sum(1 for trigger in triggers if isinstance(trigger, str)),
    }


def _add_trigger_diagnostics(diagnostics: PlannerCardBuildDiagnostics, card: NPCIntentCard) -> None:
    stats = _trigger_stats(list(card.trigger_conditions or []))
    diagnostics.structured_trigger_count += stats["structured"]
    diagnostics.legacy_trigger_count += stats["legacy"]
    metadata = card.metadata if isinstance(card.metadata, dict) else {}
    if metadata.get("trigger_source") == "default":
        diagnostics.default_triggered_card_count += 1


def _forbidden_facts_for_profile(profile: NPCProfile, fact_ids: list[str]) -> list[ForbiddenFact]:
    terms = _secret_redaction_terms(profile)
    facts: list[ForbiddenFact] = []
    for fact_id in list(dict.fromkeys(fact_ids)):
        facts.append(
            ForbiddenFact(
                fact_id=fact_id,
                label=fact_id,
                redaction_terms=tuple(terms),
                severity="critical" if fact_id in profile.plot_constraints.core_secret_ids else "high",
            )
        )
    return facts


def _secret_redaction_terms(profile: NPCProfile) -> list[str]:
    terms: set[str] = set()
    for value in (profile.private_card or {}).values():
        text = str(value or "").strip()
        if 3 <= len(text) <= 220:
            terms.add(text)
        for chunk in re.split(r"[。；;,.，、\n]+", text):
            chunk = chunk.strip()
            if 4 <= len(chunk) <= 120:
                terms.add(chunk)
    for value in list(profile.secret_ids) + list(profile.plot_constraints.core_secret_ids):
        text = str(value or "").strip()
        if 3 <= len(text) <= 120:
            terms.add(text)
    return sorted(terms, key=len, reverse=True)


def _known_fact_ids(raw: dict[str, Any], profile: NPCProfile) -> list[str]:
    allowed = set(profile.knowledge_fact_ids)
    requested = _list_strings(raw.get("known_fact_ids"))
    if not requested:
        return list(profile.knowledge_fact_ids)
    return [fact_id for fact_id in requested if fact_id in allowed]
