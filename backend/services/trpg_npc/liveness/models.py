"""Data contracts for NPC liveness.

The goal is to keep foreground work cheap: no LLM calls, no database writes and
no long memory scans. These records are small enough to attach to a
SceneBeatPlan metadata block.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class LivenessBeatType(str, Enum):
    AMBIENT = "ambient"
    REACTION = "reaction"
    INITIATIVE = "initiative"
    OFFSCREEN = "offscreen"


@dataclass(slots=True)
class LatencyBudget:
    """Foreground budget for user-perceived latency.

    Keep these limits conservative. Anything beyond this budget should run after
    the visible GM reply is already streaming/saved.
    """

    max_foreground_npcs: int = 3
    max_salient_memories_per_npc: int = 3
    max_liveness_beats: int = 2
    max_initiative_beats: int = 1
    max_policy_chars_per_npc: int = 900
    foreground_soft_budget_ms: int = 35


@dataclass(slots=True)
class LivenessCard:
    npc_id: str
    default_stance: str = "guarded"
    social_energy: float = 0.5
    proactivity: float = 0.35
    interrupt_threshold: float = 0.75
    physical_tells: list[str] = field(default_factory=list)
    speech_habits: list[str] = field(default_factory=list)
    avoidance_habits: list[str] = field(default_factory=list)
    comfort_actions: list[str] = field(default_factory=list)
    personal_stakes: list[str] = field(default_factory=list)
    daily_routine_hint: str = ""
    private_line_they_wont_cross: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExpressionMask:
    npc_id: str
    mask_id: str
    hidden_state_label: str
    visible_expression: str
    social_mask: str
    body_language: list[str] = field(default_factory=list)
    voice_guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SalientMemory:
    memory_id: str
    content: str
    relevance: float = 0.0
    influence: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BehaviorPolicy:
    npc_id: str
    dominant_state: str
    visible_expression: str
    social_mask: str
    cooperation_level: float
    deception_level: float
    aggression_level: float
    risk_tolerance: float
    proactivity: float
    interrupt_threshold: float
    preferred_tactics: list[str] = field(default_factory=list)
    avoided_tactics: list[str] = field(default_factory=list)
    dialogue_guidance: dict[str, Any] = field(default_factory=dict)
    body_language_guidance: list[str] = field(default_factory=list)
    memory_influences: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LivenessBeat:
    beat_type: LivenessBeatType
    npc_id: str
    beat: str
    priority: float = 0.5
    consumes_primary_action: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["beat_type"] = self.beat_type.value
        return data


@dataclass(slots=True)
class LivenessPreTurnBundle:
    policies_by_npc: dict[str, BehaviorPolicy] = field(default_factory=dict)
    expression_masks_by_npc: dict[str, ExpressionMask] = field(default_factory=dict)
    salient_memories_by_npc: dict[str, list[SalientMemory]] = field(default_factory=dict)
    liveness_beats: list[LivenessBeat] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_metadata(self) -> dict[str, Any]:
        return {
            "liveness_beats": [beat.to_dict() for beat in self.liveness_beats],
            "policies": {
                npc_id: policy.to_dict()
                for npc_id, policy in self.policies_by_npc.items()
            },
            "expression_masks": {
                npc_id: mask.to_dict()
                for npc_id, mask in self.expression_masks_by_npc.items()
            },
            "salient_memories": {
                npc_id: [_memory_prompt_dict(memory) for memory in memories]
                for npc_id, memories in self.salient_memories_by_npc.items()
            },
            "metadata": dict(self.metadata),
        }


def _memory_prompt_dict(memory: SalientMemory) -> dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "relevance": memory.relevance,
        "influence": memory.influence,
        "tags": list(memory.tags),
    }
