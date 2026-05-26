"""Result dataclasses returned by the NPC runtime adapter facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.trpg_npc.action_board import ActionBoard
from services.trpg_npc.models import (
    GameEvent,
    NPCProfile,
    NPCState,
    RelationshipVector,
    SceneBeatPlan,
    SceneState,
)
from services.trpg_npc.optimization.scene_beat_plan_guard import render_npc_beat_plan_section
from services.trpg_npc.orchestrator import PostTurnResult, PreTurnResult


@dataclass(slots=True)
class NPCPreTurnRuntimeResult:
    """What chatrpg needs from the foreground NPC runtime before GM generation."""

    pre_turn: PreTurnResult | None = None
    scene_state: SceneState | None = None
    profiles_by_id: dict[str, NPCProfile] = field(default_factory=dict)
    states_by_id: dict[str, NPCState] = field(default_factory=dict)
    relationships_by_npc: dict[str, dict[str, RelationshipVector]] = field(default_factory=dict)
    target_ids: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def beat_plan(self) -> SceneBeatPlan | None:
        return self.pre_turn.beat_plan if self.pre_turn else None

    def to_prompt_block(self) -> str:
        if not self.beat_plan:
            return ""
        return render_npc_beat_plan_section(self.beat_plan)


@dataclass(slots=True)
class NPCActionBoardWarmResult:
    """Summary for post-turn ActionBoard preheating."""

    post_turn: PostTurnResult | None = None
    action_board: ActionBoard | None = field(default=None, repr=False)
    committed_events: list[GameEvent] = field(default_factory=list, repr=False)
    profiles_by_id: dict[str, NPCProfile] = field(default_factory=dict, repr=False)
    scene_id: str = ""
    turn_id: int = 0
    active_npc_count: int = 0
    planned_card_ids: list[str] = field(default_factory=list)
    stored_card_count: int = 0
    runtime_writeback: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "turn_id": self.turn_id,
            "active_npc_count": self.active_npc_count,
            "planned_card_ids": list(self.planned_card_ids),
            "stored_card_count": self.stored_card_count,
            "runtime_writeback": dict(self.runtime_writeback),
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }
