"""NPC liveness layer for Runtime V2."""

from .behavior_policy import BehaviorPolicyCompiler, compile_policies_for_active_npcs
from .expression_mask import ExpressionMaskEngine
from .hot_patch_preview import apply_hot_patch_preview, apply_hot_patches_preview
from .integration import attach_liveness_to_beat_plan, build_liveness_pre_turn_bundle
from .liveness_card import liveness_card_from_npc
from .liveness_tick import LivenessTickEngine
from .memory_salience import retrieve_salient_memories
from .models import (
    BehaviorPolicy,
    ExpressionMask,
    LatencyBudget,
    LivenessBeat,
    LivenessBeatType,
    LivenessCard,
    LivenessPreTurnBundle,
    SalientMemory,
)
from .mode_transition import preview_mode
from .routine_planner import OffscreenRoutineEvent, RoutinePlanner

__all__ = [
    "BehaviorPolicy", "BehaviorPolicyCompiler", "ExpressionMask", "ExpressionMaskEngine",
    "LatencyBudget", "LivenessBeat", "LivenessBeatType", "LivenessCard", "LivenessPreTurnBundle",
    "SalientMemory", "apply_hot_patch_preview", "apply_hot_patches_preview",
    "attach_liveness_to_beat_plan", "build_liveness_pre_turn_bundle", "compile_policies_for_active_npcs",
    "liveness_card_from_npc", "LivenessTickEngine", "retrieve_salient_memories", "preview_mode",
    "OffscreenRoutineEvent", "RoutinePlanner",
]
