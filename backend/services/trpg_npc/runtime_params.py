"""Runtime configuration knobs for NPC orchestration.

Keep this separate from your existing params.py if that file already exists.
You can copy values into your own settings module instead of importing this file.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NPCRuntimeParams:
    foreground_hot_npc_timeout_ms: int = 900
    background_npc_plan_timeout_ms: int = 4000
    max_hot_npcs_per_turn: int = 1
    max_action_cards_to_scene_director: int = 4
    max_primary_npc_actions: int = 1
    max_secondary_npc_reactions: int = 2
    max_ambient_npc_mentions: int = 3
    max_clue_reveals_per_turn: int = 1
    action_card_ttl_turns: int = 3
    enable_hot_state_patch: bool = True
    enable_background_actionboard_refresh: bool = True
    enable_faction_clocks: bool = True
