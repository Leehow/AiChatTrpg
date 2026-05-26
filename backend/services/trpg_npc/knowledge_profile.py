"""Build NPC-visible knowledge profiles.

The generation prompt should receive visible_facts and private_beliefs only.
Concrete forbidden facts should generally be used by LeakChecker after
output generation, not injected into the NPC prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.trpg_context.models import ActorScope, ContextProfile, Visibility
from services.trpg_memory.memory_models import MemoryItem, MemoryKind
from services.trpg_memory.memory_store import MemoryStore


@dataclass(frozen=True)
class ActorKnowledgeProfile:
    actor: ActorScope
    visible_facts: tuple[MemoryItem, ...] = field(default_factory=tuple)
    private_beliefs: tuple[MemoryItem, ...] = field(default_factory=tuple)
    relationship_memories: tuple[MemoryItem, ...] = field(default_factory=tuple)
    withheld_memory_ids: tuple[str, ...] = field(default_factory=tuple)

    def prompt_payload(self) -> dict[str, object]:
        return {
            "actor_profile": self.actor.profile.value,
            "npc_id": self.actor.npc_id,
            "visible_facts": [m.text for m in self.visible_facts],
            "private_beliefs": [m.text for m in self.private_beliefs],
            "relationships": [m.text for m in self.relationship_memories],
            "instruction": "Use only visible_facts, private_beliefs, and relationships. Do not use unknown secrets.",
        }


class NPCKnowledgeProfileBuilder:
    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    def build(self, *, actor: ActorScope) -> ActorKnowledgeProfile:
        if actor.profile != ContextProfile.NPC or not actor.npc_id:
            raise ValueError("NPCKnowledgeProfileBuilder requires ActorScope(profile=NPC, npc_id=...)")
        memories = self.memory_store.query(campaign_id=actor.campaign_id, include_inactive=False)
        visible: list[MemoryItem] = []
        beliefs: list[MemoryItem] = []
        relationships: list[MemoryItem] = []
        withheld: list[str] = []

        for memory in memories:
            if memory.visibility in {Visibility.GM_ONLY, Visibility.SYSTEM_INTERNAL, Visibility.PARTY_KNOWN}:
                # party_known means the party knows it; NPCs do not inherit it unless
                # the memory layer separately writes an npc_private belief/fact for them.
                withheld.append(memory.memory_id)
                continue
            if memory.visibility == Visibility.NPC_PRIVATE and memory.owner_id != actor.npc_id:
                withheld.append(memory.memory_id)
                continue
            if memory.kind == MemoryKind.BELIEF or memory.kind == MemoryKind.EMOTION:
                beliefs.append(memory)
            elif memory.kind == MemoryKind.RELATIONSHIP:
                relationships.append(memory)
            else:
                visible.append(memory)

        return ActorKnowledgeProfile(
            actor=actor,
            visible_facts=tuple(visible),
            private_beliefs=tuple(beliefs),
            relationship_memories=tuple(relationships),
            withheld_memory_ids=tuple(withheld),
        )
