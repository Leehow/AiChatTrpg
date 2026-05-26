"""ContextBlock storage abstraction.

Production should back this with PostgreSQL. The InMemoryBlockStore is included
for tests and for introducing the ContextBuilder before migrations are wired.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol

from .models import BlockKind, ContextBlock


class ContextBlockStore(Protocol):
    def get_active_blocks(
        self,
        *,
        ruleset_id: str,
        campaign_id: str,
        chapter_id: str | None,
        location_id: str | None,
        npc_ids: tuple[str, ...],
        session_id: str | None,
        scene_id: str | None,
    ) -> list[ContextBlock]:
        ...

    def upsert_block(self, block: ContextBlock) -> None:
        ...


class InMemoryBlockStore:
    def __init__(self, blocks: Iterable[ContextBlock] | None = None) -> None:
        self._blocks: dict[str, ContextBlock] = {}
        for block in blocks or []:
            self.upsert_block(block)

    def upsert_block(self, block: ContextBlock) -> None:
        self._blocks[block.versioned_id] = block

    def get_active_blocks(
        self,
        *,
        ruleset_id: str,
        campaign_id: str,
        chapter_id: str | None,
        location_id: str | None,
        npc_ids: tuple[str, ...],
        session_id: str | None,
        scene_id: str | None,
    ) -> list[ContextBlock]:
        # Keep the newest version of each block_id that matches current scope.
        candidates: dict[str, ContextBlock] = {}
        allowed_scopes = {
            ("global", "global"),
            ("ruleset", ruleset_id),
            ("campaign", campaign_id),
        }
        if chapter_id:
            allowed_scopes.add(("chapter", chapter_id))
        if location_id:
            allowed_scopes.add(("location", location_id))
        if session_id:
            allowed_scopes.add(("session", session_id))
        if scene_id:
            allowed_scopes.add(("scene", scene_id))
        for npc_id in npc_ids:
            allowed_scopes.add(("npc", npc_id))

        for block in self._blocks.values():
            if (block.scope_type, block.scope_id) not in allowed_scopes:
                continue
            old = candidates.get(block.block_id)
            if old is None or block.version > old.version:
                candidates[block.block_id] = block
        return list(candidates.values())


def group_by_kind(blocks: Iterable[ContextBlock]) -> dict[BlockKind, list[ContextBlock]]:
    grouped: dict[BlockKind, list[ContextBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.kind].append(block)
    return grouped
