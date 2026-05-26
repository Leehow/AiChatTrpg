"""Hardening helpers for AiChatTrpg NPC Runtime V2.

These modules are designed to be copied into ``backend/services/trpg_npc``
and wired into the existing runtime adapter, action board, persistence and
scene context code.  They intentionally accept both dictionaries and simple
objects so they can be integrated incrementally with the current codebase.
"""

from .safe_projection import prompt_safe_active_npcs_hardened, scan_prompt_safety_violations
from .event_classifier import classify_player_text_to_events
from .action_board_guard import filter_action_cards_for_turn
from .secret_guard import ForbiddenContentGuard, ForbiddenFact
from .writeback_guard import apply_runtime_snapshot_guarded, RuntimeWritebackPolicy
from .memory_compaction import compact_npc_memories

__all__ = [
    "prompt_safe_active_npcs_hardened",
    "scan_prompt_safety_violations",
    "classify_player_text_to_events",
    "filter_action_cards_for_turn",
    "ForbiddenContentGuard",
    "ForbiddenFact",
    "apply_runtime_snapshot_guarded",
    "RuntimeWritebackPolicy",
    "compact_npc_memories",
]
