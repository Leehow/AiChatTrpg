"""Visibility filtering for prompt construction.

TRPG prompts must not leak GM-only facts into player or NPC contexts. Treat
visibility as a first-class cache dimension: do not reuse a prefix across
profiles with different visibility privileges.
"""

from __future__ import annotations

from .models import ActorScope, ContextBlock, ContextProfile, Visibility


def visibility_signature(actor: ActorScope) -> str:
    if actor.profile == ContextProfile.NPC:
        return f"npc:{actor.npc_id or 'unknown'}"
    if actor.profile == ContextProfile.PLAYER:
        return f"party:{actor.party_id or 'default'}"
    return actor.profile.value


def can_read(block: ContextBlock, actor: ActorScope) -> bool:
    visibility = block.visibility

    if actor.profile == ContextProfile.GM:
        return visibility in {
            Visibility.PUBLIC,
            Visibility.PARTY_KNOWN,
            Visibility.GM_ONLY,
            Visibility.NPC_PRIVATE,
            Visibility.SYSTEM_INTERNAL,
        }

    if actor.profile == ContextProfile.PLAYER:
        return visibility in {Visibility.PUBLIC, Visibility.PARTY_KNOWN}

    if actor.profile == ContextProfile.NPC:
        if visibility == Visibility.PUBLIC:
            return True
        if visibility == Visibility.NPC_PRIVATE:
            return block.owner_id == actor.npc_id
        # NPCs should not receive party-known knowledge unless it is also public
        # or explicitly copied into their private knowledge by the memory layer.
        return False

    if actor.profile == ContextProfile.MEMORY_EXTRACTOR:
        # Extractor needs enough to classify visibility and compare known state,
        # but it should not see unrelated NPC secrets unless explicitly added.
        return visibility in {
            Visibility.PUBLIC,
            Visibility.PARTY_KNOWN,
            Visibility.GM_ONLY,
            Visibility.SYSTEM_INTERNAL,
        }

    if actor.profile == ContextProfile.RULE_ADJUDICATOR:
        # Rule adjudication should avoid plot secrets and personal NPC memories.
        return visibility in {Visibility.PUBLIC, Visibility.PARTY_KNOWN}

    return False
