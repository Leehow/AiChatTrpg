"""Structured contract for one generated TRPG turn.

Model output should be parsed into TurnOutputContract before state or memory
is mutated. Narration is not authority; confirmed state_changes are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from services.trpg_context.models import Visibility
from services.trpg_memory.memory_models import MemoryProposal


class NextActor(str, Enum):
    PLAYER = "player"
    NPC = "npc"
    GM = "gm"
    SYSTEM = "system"
    ANOTHER_PLAYER = "another_player"


class StateChangeType(str, Enum):
    ENTITY_LOCATION = "entity_location"
    ITEM_TRANSFER = "item_transfer"
    NPC_ATTITUDE = "npc_attitude"
    NPC_EMOTION = "npc_emotion"
    CHARACTER_DAMAGE = "character_damage"
    RESOURCE_CHANGE = "resource_change"
    CLUE_DISCOVERED = "clue_discovered"
    SCENE_TRANSITION = "scene_transition"
    TIME_ADVANCE = "time_advance"
    STATUS_EFFECT = "status_effect"
    CUSTOM = "custom"


class StateOperation(str, Enum):
    SET = "set"
    INCREMENT = "increment"
    APPEND_UNIQUE = "append_unique"
    REMOVE = "remove"
    MERGE = "merge"


@dataclass(frozen=True)
class RuleCheckRequest:
    check_id: str
    ruleset_id: str
    skill_or_stat: str
    difficulty: str | int
    reason: str
    actor_id: str | None = None
    target_id: str | None = None


@dataclass(frozen=True)
class RuleCheckResult:
    check_id: str
    ruleset_id: str
    roll_expression: str
    rolled: int | float
    target: int | float | None
    outcome: Literal["critical_success", "success", "partial", "failure", "fumble", "unknown"]
    explanation: str = ""


@dataclass(frozen=True)
class NPCMessage:
    npc_id: str
    speech: str
    action: str = ""
    emotion: str | None = None
    intent: str | None = None
    attitude_delta: int | float | None = None
    should_escalate: bool = False


@dataclass(frozen=True)
class StateChange:
    change_id: str
    type: StateChangeType
    target_id: str
    operation: StateOperation
    value: Any
    path: tuple[str, ...] = field(default_factory=tuple)
    actor_id: str | None = None
    source_turn_id: str | None = None
    visibility: Visibility = Visibility.GM_ONLY
    confidence: float = 1.0
    reason: str = ""
    requires_rule_confirmation: bool = False
    rule_check_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SuggestedAction:
    label: str
    intent: str
    risk: str | None = None


@dataclass(frozen=True)
class TurnOutputContract:
    turn_id: str
    narration: str
    state_changes: tuple[StateChange, ...] = field(default_factory=tuple)
    memory_proposals: tuple[MemoryProposal, ...] = field(default_factory=tuple)
    npc_messages: tuple[NPCMessage, ...] = field(default_factory=tuple)
    rule_check_requests: tuple[RuleCheckRequest, ...] = field(default_factory=tuple)
    rule_check_results: tuple[RuleCheckResult, ...] = field(default_factory=tuple)
    next_actor: NextActor = NextActor.PLAYER
    waiting_for: str = "player_decision"
    suggested_actions: tuple[SuggestedAction, ...] = field(default_factory=tuple)
    raw_model_output: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def transcript_text_for_validation(self, player_input: str = "") -> str:
        npc_text = "\n".join(
            f"{msg.npc_id}: {msg.action} {msg.speech}".strip()
            for msg in self.npc_messages
        )
        return "\n".join(part for part in [player_input, self.narration, npc_text] if part)


def validate_turn_contract(contract: TurnOutputContract) -> tuple[str, ...]:
    issues: list[str] = []
    if not contract.turn_id:
        issues.append("turn_id is required")
    if not contract.narration.strip() and not contract.npc_messages:
        issues.append("contract should contain narration or npc_messages")
    if len(contract.suggested_actions) > 4:
        issues.append("suggested_actions should be limited to 4 or fewer")
    change_ids = [change.change_id for change in contract.state_changes]
    if len(change_ids) != len(set(change_ids)):
        issues.append("state_change change_id values must be unique")
    for change in contract.state_changes:
        if change.source_turn_id and change.source_turn_id != contract.turn_id:
            issues.append(f"state_change {change.change_id} source_turn_id does not match contract.turn_id")
    return tuple(issues)
