"""Lifecycle operations for committed memories.

Supports rollback, correction, invalidate, and supersede without destroying
provenance. This is critical for AI-run tabletop sessions where players often
clarify intent after the model misinterprets a turn.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .memory_identity import stable_idempotency_key, stable_memory_id_from_key
from .memory_models import MemoryItem, MemoryProposal, MemoryStatus
from .memory_store import MemoryStore


@dataclass(frozen=True)
class LifecycleResult:
    updated: tuple[MemoryItem, ...]
    notes: tuple[str, ...] = ()


class MemoryLifecycleService:
    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    def rollback_by_turn(self, *, campaign_id: str, turn_id: str, reason: str) -> LifecycleResult:
        active = self.memory_store.query(campaign_id=campaign_id, include_inactive=False)
        updated: list[MemoryItem] = []
        for item in active:
            if turn_id in item.source_turn_ids or item.created_at_turn == turn_id:
                rolled = item.with_status(
                    MemoryStatus.ROLLED_BACK,
                    invalidated_by_turn_id=turn_id,
                    correction_reason=reason,
                )
                updated.append(self.memory_store.replace(rolled))
        return LifecycleResult(updated=tuple(updated), notes=(f"rolled back memories from turn {turn_id}",))

    def invalidate(self, *, memory_id: str, turn_id: str, reason: str) -> MemoryItem:
        item = self.memory_store.get(memory_id)
        if item is None:
            raise KeyError(f"unknown memory_id: {memory_id}")
        invalidated = item.with_status(
            MemoryStatus.INVALIDATED,
            invalidated_by_turn_id=turn_id,
            correction_reason=reason,
        )
        return self.memory_store.replace(invalidated)

    def supersede(
        self,
        *,
        old_memory_id: str,
        campaign_id: str,
        new_proposal: MemoryProposal,
        correction_turn_id: str,
        reason: str,
    ) -> tuple[MemoryItem, MemoryItem]:
        old = self.memory_store.get(old_memory_id)
        if old is None:
            raise KeyError(f"unknown memory_id: {old_memory_id}")

        new_key = new_proposal.idempotency_key or stable_idempotency_key(campaign_id, new_proposal)
        new_id = stable_memory_id_from_key(campaign_id, new_key)
        new_item = MemoryItem.from_proposal(
            memory_id=new_id,
            campaign_id=campaign_id,
            proposal=new_proposal,
        )
        new_item = replace(
            new_item,
            supersedes_memory_id=old.memory_id,
            correction_reason=reason,
            created_at_turn=correction_turn_id,
            idempotency_key=new_key,
        )
        new_item = self.memory_store.add(new_item)
        old_item = old.with_status(
            MemoryStatus.SUPERSEDED,
            superseded_by=new_item.memory_id,
            invalidated_by_turn_id=correction_turn_id,
            correction_reason=reason,
        )
        old_item = self.memory_store.replace(old_item)
        return old_item, new_item
