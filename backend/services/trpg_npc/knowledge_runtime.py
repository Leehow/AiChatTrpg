"""Runtime bridge from table-backed memories to NPC knowledge prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession
from services.trpg_context.models import ActorScope, ContextProfile
from services.trpg_memory.memory_models import MemoryItem
from services.trpg_memory.runtime_store import (
    StaticMemoryStore,
    list_session_memory_items,
)
from services.trpg_npc.knowledge_profile import (
    ActorKnowledgeProfile,
    NPCKnowledgeProfileBuilder,
)
from services.trpg_npc.leak_checker import LeakWarning


@dataclass(frozen=True)
class NPCKnowledgeRuntime:
    """NPC-scoped visible knowledge plus withheld memories for auditing."""

    profiles_by_npc_id: dict[str, ActorKnowledgeProfile] = field(default_factory=dict)
    forbidden_memories_by_npc_id: dict[str, tuple[MemoryItem, ...]] = field(default_factory=dict)
    loaded_memory_count: int = 0
    error: str = ""

    def prompt_payloads_by_npc_id(self) -> dict[str, dict[str, object]]:
        return {
            npc_id: profile.prompt_payload()
            for npc_id, profile in self.profiles_by_npc_id.items()
        }

    def summary(self) -> dict[str, Any]:
        return {
            "profile_count": len(self.profiles_by_npc_id),
            "loaded_memory_count": int(self.loaded_memory_count),
            "visible_memory_count": sum(
                len(profile.visible_facts)
                + len(profile.private_beliefs)
                + len(profile.relationship_memories)
                for profile in self.profiles_by_npc_id.values()
            ),
            "withheld_memory_count": sum(
                len(memories)
                for memories in self.forbidden_memories_by_npc_id.values()
            ),
            "error": self.error,
        }


async def build_npc_knowledge_runtime(
    db: AsyncSession | Any,
    session: GameSession,
    *,
    npc_ids: Iterable[str],
    scene_id: str | None = None,
    limit: int = 300,
) -> NPCKnowledgeRuntime:
    """Load committed memories and build per-NPC knowledge profiles.

    The prompt side receives only `ActorKnowledgeProfile.prompt_payload()`.
    Withheld memories are returned separately for `LeakChecker` and should not
    be injected into model prompts.
    """

    if db is None:
        return NPCKnowledgeRuntime(error="missing_db")
    ids = tuple(dict.fromkeys(str(npc_id).strip() for npc_id in npc_ids if str(npc_id).strip()))
    if not ids:
        return NPCKnowledgeRuntime()

    try:
        items = await list_session_memory_items(
            db,
            str(session.id),
            include_inactive=False,
            limit=limit,
        )
    except Exception as exc:
        return NPCKnowledgeRuntime(error=f"{type(exc).__name__}: {exc}")

    store = StaticMemoryStore(items)
    builder = NPCKnowledgeProfileBuilder(store)
    profiles: dict[str, ActorKnowledgeProfile] = {}
    forbidden: dict[str, tuple[MemoryItem, ...]] = {}
    for npc_id in ids:
        profile = builder.build(
            actor=ActorScope(
                profile=ContextProfile.NPC,
                campaign_id=str(session.id),
                session_id=str(session.id),
                scene_id=scene_id or None,
                npc_id=npc_id,
            )
        )
        profiles[npc_id] = profile
        forbidden[npc_id] = tuple(
            item
            for memory_id in profile.withheld_memory_ids
            for item in [store.get(memory_id)]
            if item is not None
        )

    return NPCKnowledgeRuntime(
        profiles_by_npc_id=profiles,
        forbidden_memories_by_npc_id=forbidden,
        loaded_memory_count=len(items),
    )


def leak_warnings_to_dict(
    warnings: Iterable[LeakWarning],
    *,
    include_terms: bool = False,
) -> list[dict[str, Any]]:
    """Serialize leak warnings without exposing secret text by default."""

    payload: list[dict[str, Any]] = []
    for warning in warnings:
        item = {
            "memory_id": warning.memory_id,
            "severity": warning.severity,
            "reason": warning.reason,
        }
        if include_terms:
            item["matched_terms"] = list(warning.matched_terms)
        payload.append(item)
    return payload
