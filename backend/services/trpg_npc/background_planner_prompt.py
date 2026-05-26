"""Prompt assembly and NPC selection for the background planner."""

from __future__ import annotations

import json
from typing import Any

from services.trpg_npc.background_planner_constants import (
    _ALLOWED_STRUCTURED_EVENT_TYPES,
    _ALLOWED_TOPIC_TAGS,
    _ALLOWED_TRIGGERS,
    _MAX_NPCS,
    _MAX_TEXT_CHARS,
)
from services.trpg_npc.models import NPCProfile, NPCState, NPCTier


def select_background_planner_npc_ids(
    profiles_by_id: dict[str, NPCProfile],
    *,
    active_npcs: list[dict[str, Any]],
    max_npcs: int = _MAX_NPCS,
) -> list[str]:
    """Select important active NPCs in stable scene order."""

    active_order = [
        str(npc.get("key") or npc.get("name") or "").strip()
        for npc in active_npcs
        if isinstance(npc, dict)
    ]
    order_index = {npc_id: index for index, npc_id in enumerate(active_order) if npc_id}

    candidates: list[tuple[int, int, str]] = []
    for npc_id, profile in profiles_by_id.items():
        if profile.tier not in {NPCTier.SUPPORTING, NPCTier.MAJOR}:
            continue
        tier_rank = 0 if profile.tier == NPCTier.MAJOR else 1
        candidates.append((tier_rank, order_index.get(npc_id, 9999), npc_id))
    candidates.sort()
    return [npc_id for _tier, _order, npc_id in candidates[:max(0, int(max_npcs or 0))]]


def build_background_planner_prompt(
    *,
    profiles_by_id: dict[str, NPCProfile],
    states_by_id: dict[str, NPCState],
    relationships_by_npc: dict[str, dict[str, Any]],
    knowledge_profiles_by_npc_id: dict[str, Any] | None = None,
    scene_id: str,
    turn_id: int,
    player_text: str,
    gm_reply: str,
) -> str:
    knowledge_profiles_by_npc_id = knowledge_profiles_by_npc_id or {}
    npcs: list[dict[str, Any]] = []
    for npc_id, profile in profiles_by_id.items():
        state = states_by_id.get(npc_id)
        rels = relationships_by_npc.get(npc_id) or {}
        npcs.append({
            "npc_id": npc_id,
            "name": profile.name,
            "tier": profile.tier.value,
            "role": profile.narrative_role,
            "public_card": profile.public_card,
            "knowledge_profile": knowledge_profiles_by_npc_id.get(npc_id) or {},
            "state": state.to_dict() if state is not None else {},
            "relationships": {
                target_id: rel.to_dict() if hasattr(rel, "to_dict") else dict(rel)
                for target_id, rel in rels.items()
                if target_id
            },
            "plot_constraints": profile.plot_constraints.to_dict(),
        })
    return (
        "## Scene\n"
        + json.dumps({"scene_id": scene_id, "turn_id": turn_id}, ensure_ascii=False)
        + "\n\n## Allowed structured event_types\n"
        + json.dumps(sorted(_ALLOWED_STRUCTURED_EVENT_TYPES), ensure_ascii=False)
        + "\n\n## Allowed topic_tags\n"
        + json.dumps(sorted(_ALLOWED_TOPIC_TAGS), ensure_ascii=False)
        + "\n\n## Legacy trigger strings, only if a structured trigger is impossible\n"
        + json.dumps(sorted(_ALLOWED_TRIGGERS), ensure_ascii=False)
        + "\n\n## NPCs to plan for\n"
        + json.dumps(npcs, ensure_ascii=False, indent=2)
        + "\n\n## Player input this turn\n"
        + (player_text or "")[:_MAX_TEXT_CHARS]
        + "\n\n## GM reply this turn\n"
        + (gm_reply or "")[:_MAX_TEXT_CHARS]
    )
