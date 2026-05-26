"""NPC ActionBoard: cached, triggerable predicted NPC actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .optimization.action_board_guard import filter_action_cards_for_turn
from .optimization.common import to_plain_data
from .models import (
    ActionProposal,
    ActionType,
    GameEvent,
    NPCIntentCard,
    PlotConstraints,
    ProposalStatus,
)


@dataclass(slots=True)
class ActionBoardMatch:
    card: NPCIntentCard
    matched_triggers: list[Any] = field(default_factory=list)
    score: float = 0.0


class TriggerMatcher:
    """Derive coarse trigger tags from the current player event."""

    SENSITIVE_WORDS = ("邪教", "仪式", "秘密", "失踪", "凶手", "cult", "ritual", "secret", "missing")
    EVIDENCE_WORDS = ("符号", "证据", "照片", "地图", "信", "账本", "symbol", "evidence", "photo", "map", "letter")
    THREAT_WORDS = ("威胁", "杀", "打", "刀", "枪", "attack", "kill", "threat", "weapon")
    OFFER_WORDS = ("钱", "报酬", "交易", "贿赂", "pay", "deal", "bribe", "reward")
    LEAVE_WORDS = ("离开", "走", "退出", "leave", "exit", "go away")

    def derive_tags(self, event: GameEvent) -> list[str]:
        tags = [event.type.lower()]
        text = f"{event.content} {' '.join(str(v) for v in event.payload.values())}".lower()
        if event.target_ids:
            tags.append("player_targets_npc")
        if any(w.lower() in text for w in self.SENSITIVE_WORDS):
            tags.extend(["player_asks_sensitive_question", "player_mentions_secret"])
        if any(w.lower() in text for w in self.EVIDENCE_WORDS):
            tags.extend(["player_reveals_evidence", "player_mentions_symbol"])
        if any(w.lower() in text for w in self.THREAT_WORDS):
            tags.extend(["player_threatens", "physical_threat"])
        if any(w.lower() in text for w in self.OFFER_WORDS):
            tags.append("player_offers_deal")
        if any(w.lower() in text for w in self.LEAVE_WORDS):
            tags.append("player_attempts_to_leave")
        return list(dict.fromkeys(tags))


class ActionBoard:
    """In-memory action board.

    Replace this with a Redis/Postgres-backed repository in production. The
    interface is intentionally small so swapping storage is straightforward.
    """

    def __init__(self, trigger_matcher: TriggerMatcher | None = None):
        self._cards_by_scene: dict[str, list[NPCIntentCard]] = {}
        self.trigger_matcher = trigger_matcher or TriggerMatcher()

    def upsert(self, scene_id: str, cards: Iterable[NPCIntentCard]) -> None:
        existing = {c.card_id: c for c in self._cards_by_scene.get(scene_id, [])}
        for card in cards:
            existing[card.card_id] = card
        self._cards_by_scene[scene_id] = list(existing.values())

    def list_cards(self, scene_id: str) -> list[NPCIntentCard]:
        return list(self._cards_by_scene.get(scene_id, []))

    def expire_old(self, scene_id: str, turn_id: int) -> None:
        kept: list[NPCIntentCard] = []
        for card in self._cards_by_scene.get(scene_id, []):
            if card.valid_until_turn < turn_id:
                card.status = ProposalStatus.EXPIRED
            else:
                kept.append(card)
        self._cards_by_scene[scene_id] = kept

    def match(
        self,
        scene_id: str,
        event: GameEvent,
        active_npc_ids: set[str] | None = None,
        limit: int = 6,
        events: list[Any] | None = None,
    ) -> list[ActionBoardMatch]:
        active_npc_ids = active_npc_ids or set()
        scene_cards = self._cards_by_scene.get(scene_id, [])
        if events:
            guarded = filter_action_cards_for_turn(
                (
                    card for card in scene_cards
                    if not active_npc_ids or card.npc_id in active_npc_ids
                ),
                events=events,
                player_text=event.content,
                current_turn=event.turn_id,
                current_scene_id=scene_id,
                max_cards=limit,
            )
            return [
                ActionBoardMatch(
                    card=match.card,
                    matched_triggers=to_plain_data(match.matched_triggers) or [],
                    score=match.score,
                )
                for match in guarded
            ]

        tags = set(self.trigger_matcher.derive_tags(event))
        matches: list[ActionBoardMatch] = []
        for card in scene_cards:
            if not card.is_valid_for_turn(event.turn_id):
                continue
            if active_npc_ids and card.npc_id not in active_npc_ids:
                continue
            condition_set = {
                trigger.strip()
                for trigger in card.trigger_conditions
                if isinstance(trigger, str) and trigger.strip()
            }
            matched = sorted(condition_set.intersection(tags))
            # Direct targeting is strong even if card only says player_targets_npc.
            if card.npc_id in event.target_ids and "player_targets_npc" in condition_set:
                if "player_targets_npc" not in matched:
                    matched.append("player_targets_npc")
            if not matched:
                continue
            score = card.priority + 0.15 * len(matched)
            matches.append(ActionBoardMatch(card=card, matched_triggers=matched, score=score))
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]

    def proposals_from_matches(self, matches: Iterable[ActionBoardMatch]) -> list[ActionProposal]:
        proposals: list[ActionProposal] = []
        for match in matches:
            proposal = match.card.preferred_action
            proposal.source_card_id = match.card.card_id
            proposal.priority = max(proposal.priority, match.score)
            proposal.known_fact_ids = list(dict.fromkeys(proposal.known_fact_ids + match.card.known_fact_ids))
            proposal.forbidden_fact_ids = list(dict.fromkeys(proposal.forbidden_fact_ids + match.card.forbidden_fact_ids))
            proposals.append(proposal)
        return proposals

    def to_dict(self) -> dict:
        """Serialize the board into JSON-compatible storage."""

        return {
            "version": 1,
            "scenes": {
                scene_id: [card.to_dict() for card in cards]
                for scene_id, cards in self._cards_by_scene.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "ActionBoard":
        """Best-effort load from JSON-compatible storage."""

        board = cls()
        if not isinstance(data, dict):
            return board
        scenes = data.get("scenes")
        if not isinstance(scenes, dict):
            return board
        for scene_id, raw_cards in scenes.items():
            if not isinstance(raw_cards, list):
                continue
            cards = [_intent_card_from_dict(raw) for raw in raw_cards]
            board._cards_by_scene[str(scene_id)] = [card for card in cards if card is not None]
        return board


def _intent_card_from_dict(raw: dict) -> NPCIntentCard | None:
    if not isinstance(raw, dict):
        return None
    preferred = _proposal_from_dict(raw.get("preferred_action"))
    if preferred is None:
        return None
    fallback = [
        proposal for proposal in (
            _proposal_from_dict(item)
            for item in raw.get("fallback_actions", [])
            if isinstance(item, dict)
        )
        if proposal is not None
    ]
    return NPCIntentCard(
        card_id=str(raw.get("card_id") or ""),
        npc_id=str(raw.get("npc_id") or ""),
        based_on_turn_id=_int(raw.get("based_on_turn_id"), 0),
        valid_until_turn=_int(raw.get("valid_until_turn"), 0),
        priority=_float(raw.get("priority"), 0.5),
        trigger_conditions=_trigger_conditions(raw.get("trigger_conditions")),
        preferred_action=preferred,
        fallback_actions=fallback,
        motivation=str(raw.get("motivation") or ""),
        known_fact_ids=_list_strings(raw.get("known_fact_ids")),
        forbidden_fact_ids=_list_strings(raw.get("forbidden_fact_ids")),
        plot_constraints=_plot_constraints_from_dict(raw.get("plot_constraints")),
        status=_proposal_status(raw.get("status")),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _proposal_from_dict(raw: dict | None) -> ActionProposal | None:
    if not isinstance(raw, dict):
        return None
    actor_id = str(raw.get("actor_id") or "").strip()
    if not actor_id:
        return None
    return ActionProposal(
        actor_id=actor_id,
        intent=str(raw.get("intent") or ""),
        action_type=_action_type(raw.get("action_type")),
        target_ids=_list_strings(raw.get("target_ids")),
        priority=_float(raw.get("priority"), 0.5),
        player_facing=raw.get("player_facing") if isinstance(raw.get("player_facing"), dict) else {},
        gm_facing=raw.get("gm_facing") if isinstance(raw.get("gm_facing"), dict) else {},
        mechanics=raw.get("mechanics") if isinstance(raw.get("mechanics"), dict) else {},
        state_updates=raw.get("state_updates") if isinstance(raw.get("state_updates"), list) else [],
        memory_writes=raw.get("memory_writes") if isinstance(raw.get("memory_writes"), list) else [],
        reveal_fact_ids=_list_strings(raw.get("reveal_fact_ids")),
        known_fact_ids=_list_strings(raw.get("known_fact_ids")),
        forbidden_fact_ids=_list_strings(raw.get("forbidden_fact_ids")),
        source_card_id=str(raw.get("source_card_id") or "") or None,
        status=_proposal_status(raw.get("status")),
        consume_action_budget=bool(raw.get("consume_action_budget", True)),
    )


def _plot_constraints_from_dict(raw: dict | None) -> PlotConstraints:
    if not isinstance(raw, dict):
        return PlotConstraints()
    constraints = PlotConstraints()
    for key in (
        "can_reveal_core_secret",
        "can_attack_players",
        "can_flee",
        "must_preserve_clue_path",
        "max_clue_reveals_per_turn",
        "minimum_clue_output",
        "forbidden_fact_ids",
        "core_secret_ids",
        "blocked_escalations",
        "allowed_escalations",
    ):
        if key in raw:
            setattr(constraints, key, raw[key])
    return constraints


def _action_type(value) -> ActionType:
    try:
        return ActionType(value)
    except Exception:
        return ActionType.SAY


def _proposal_status(value) -> ProposalStatus:
    try:
        return ProposalStatus(value)
    except Exception:
        return ProposalStatus.PROPOSED


def _list_strings(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _trigger_conditions(value) -> list[Any]:
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
            elif isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
