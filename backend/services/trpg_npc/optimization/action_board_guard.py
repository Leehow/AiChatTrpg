"""Structured ActionBoard matching and lifecycle guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .common import clamp, get_value, stable_list, to_plain_data
from .event_classifier import STRING_TRIGGER_TO_EVENT_TYPES


@dataclass(slots=True)
class ActionCardMatch:
    card: Any
    card_id: str
    npc_id: str
    score: float
    matched_triggers: list[Any] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "npc_id": self.npc_id,
            "score": round(self.score, 4),
            "matched_triggers": to_plain_data(self.matched_triggers),
            "reasons": list(self.reasons),
        }


def _card_id(card: Any) -> str:
    return str(get_value(card, "card_id") or get_value(card, "id") or f"card:{id(card)}")


def _npc_id(card: Any) -> str:
    return str(get_value(card, "npc_id") or get_value(card, "actor_id") or "unknown_npc")


def _card_scene_id(card: Any) -> str | None:
    return get_value(card, "scene_id") or get_value(get_value(card, "preferred_action"), "scene_id")


def _trigger_conditions(card: Any) -> list[Any]:
    return stable_list(get_value(card, "trigger_conditions"))


def _priority(card: Any) -> float:
    return clamp(get_value(card, "priority", 0.5), 0.0, 1.0)


def _based_on_turn(card: Any) -> int | None:
    value = get_value(card, "based_on_turn_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _valid_until_turn(card: Any) -> int | None:
    value = get_value(card, "valid_until_turn")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_type(event: Any) -> str:
    return str(get_value(event, "type", ""))


def _event_target_ids(event: Any) -> set[str]:
    return {str(v) for v in stable_list(get_value(event, "target_ids"))}


def _event_tags(event: Any) -> set[str]:
    payload = get_value(event, "payload", {}) or {}
    return {str(v) for v in stable_list(get_value(payload, "topic_tags"))}


def _event_confidence(event: Any) -> float:
    payload = get_value(event, "payload", {}) or {}
    return clamp(get_value(payload, "confidence", 0.5), 0.0, 1.0)


def _matches_structured_trigger(trigger: Mapping[str, Any], events: list[Any], card_npc_id: str) -> tuple[bool, list[str]]:
    expected_types = {str(v) for v in stable_list(trigger.get("event_type") or trigger.get("event_types"))}
    expected_tags = {str(v) for v in stable_list(trigger.get("topic_tags"))}
    expected_targets = {str(v) for v in stable_list(trigger.get("target_ids"))}
    min_confidence = clamp(trigger.get("min_confidence", 0.0), 0.0, 1.0)
    require_target = bool(trigger.get("require_target", False))

    reasons: list[str] = []
    for event in events:
        event_type = _event_type(event)
        if expected_types and event_type not in expected_types:
            continue
        if _event_confidence(event) < min_confidence:
            continue
        event_tags = _event_tags(event)
        if expected_tags and not expected_tags.intersection(event_tags):
            continue
        event_targets = _event_target_ids(event)
        if expected_targets and not expected_targets.intersection(event_targets):
            continue
        if require_target and card_npc_id not in event_targets:
            continue
        if event_targets and card_npc_id not in event_targets and not expected_targets:
            # An event aimed clearly at another NPC should not trigger this NPC's card.
            continue
        reasons.append(f"event:{event_type}")
        if event_tags:
            reasons.append(f"tags:{','.join(sorted(event_tags))}")
        return True, reasons
    return False, []


def _matches_string_trigger(trigger: str, events: list[Any], player_text: str, card_npc_id: str = "") -> tuple[bool, list[str]]:
    normalized = trigger.strip().lower()
    if normalized == "player_targets_npc":
        for event in events:
            event_targets = _event_target_ids(event)
            if card_npc_id and card_npc_id in event_targets:
                return True, [f"trigger:{normalized}", f"target:{card_npc_id}"]
        return False, []

    expected_types = STRING_TRIGGER_TO_EVENT_TYPES.get(normalized, set())
    if expected_types:
        matched_types: set[str] = set()
        for event in events:
            event_type = _event_type(event)
            if event_type not in expected_types:
                continue
            event_targets = _event_target_ids(event)
            if event_targets and card_npc_id and card_npc_id not in event_targets:
                continue
            matched_types.add(event_type)
        if matched_types:
            return True, [f"trigger:{normalized}", f"event_types:{','.join(sorted(matched_types))}"]
        if any(_event_type(event) in expected_types for event in events):
            return False, []

    # Conservative raw-text fallback for legacy cards.  This should be used only
    # when structured events are unavailable or the card predates structured triggers.
    text = (player_text or "").lower()
    fallback_keywords = {
        "player_asks_sensitive_question": ["邪教", "秘密", "失踪", "符号", "cult", "secret", "missing"],
        "player_mentions_secret": ["秘密", "主谋", "幕后", "secret", "leader"],
        "player_mentions_cult_symbol": ["符号", "徽记", "图案", "symbol", "sigil"],
        "player_is_aggressive": ["威胁", "逼问", "拔枪", "攻击", "threaten", "attack"],
        "player_offers_protection": ["保护", "救你", "protect", "safe"],
        "player_attempts_to_leave": ["离开", "出门", "leave", "exit"],
    }
    for keyword in fallback_keywords.get(normalized, []):
        if keyword.lower() in text:
            return True, [f"legacy_text_trigger:{normalized}", f"keyword:{keyword}"]
    return False, []


def is_card_lifecycle_valid(
    card: Any,
    *,
    current_turn: int,
    current_scene_id: str | None,
    max_future_skew_turns: int = 0,
) -> tuple[bool, list[str]]:
    """Validate card freshness and scene applicability."""

    reasons: list[str] = []
    scene_id = _card_scene_id(card)
    if scene_id and current_scene_id and scene_id != current_scene_id:
        return False, [f"scene_mismatch:{scene_id}!={current_scene_id}"]

    based_on = _based_on_turn(card)
    if based_on is not None and based_on > current_turn + max_future_skew_turns:
        return False, [f"future_card:based_on_turn={based_on}:current={current_turn}"]

    valid_until = _valid_until_turn(card)
    if valid_until is not None and valid_until < current_turn:
        return False, [f"expired:valid_until={valid_until}:current={current_turn}"]

    if based_on is not None:
        reasons.append(f"based_on_turn:{based_on}")
    if valid_until is not None:
        reasons.append(f"valid_until_turn:{valid_until}")
    return True, reasons


def match_card_against_events(
    card: Any,
    *,
    events: list[Any],
    player_text: str,
    current_turn: int,
    current_scene_id: str | None,
) -> ActionCardMatch | None:
    ok, lifecycle_reasons = is_card_lifecycle_valid(
        card,
        current_turn=current_turn,
        current_scene_id=current_scene_id,
    )
    if not ok:
        return None

    triggers = _trigger_conditions(card)
    if not triggers:
        return None

    matched_triggers: list[Any] = []
    reasons = list(lifecycle_reasons)
    npc_id = _npc_id(card)

    for trigger in triggers:
        if isinstance(trigger, Mapping):
            matched, trigger_reasons = _matches_structured_trigger(trigger, events, npc_id)
        else:
            matched, trigger_reasons = _matches_string_trigger(str(trigger), events, player_text, npc_id)
        if matched:
            matched_triggers.append(trigger)
            reasons.extend(trigger_reasons)

    if not matched_triggers:
        return None

    based_on = _based_on_turn(card)
    stale_penalty = 0.0
    if based_on is not None:
        stale_penalty = min(max(current_turn - based_on - 1, 0) * 0.04, 0.2)
    score = max(0.0, _priority(card) + 0.08 * len(matched_triggers) - stale_penalty)
    return ActionCardMatch(
        card=card,
        card_id=_card_id(card),
        npc_id=npc_id,
        score=score,
        matched_triggers=matched_triggers,
        reasons=reasons,
    )


def filter_action_cards_for_turn(
    cards: Iterable[Any],
    *,
    events: list[Any],
    player_text: str,
    current_turn: int,
    current_scene_id: str | None,
    max_cards: int = 4,
) -> list[ActionCardMatch]:
    """Return top matching cards for the current pre-turn frame."""

    matches: list[ActionCardMatch] = []
    seen_card_ids: set[str] = set()
    for card in cards or []:
        match = match_card_against_events(
            card,
            events=events,
            player_text=player_text,
            current_turn=current_turn,
            current_scene_id=current_scene_id,
        )
        if not match:
            continue
        if match.card_id in seen_card_ids:
            continue
        seen_card_ids.add(match.card_id)
        matches.append(match)

    matches.sort(key=lambda m: (m.score, m.card_id), reverse=True)
    return matches[:max_cards]
