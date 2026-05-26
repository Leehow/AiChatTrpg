"""In-memory memory store and protocol.

Replace InMemoryMemoryStore with a PostgreSQL repository when wiring this into
production. The protocol intentionally exposes only lifecycle-safe operations.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import replace
from typing import Iterable, Protocol

from services.trpg_context.models import Visibility
from .memory_models import MemoryItem, MemoryKind, MemoryStatus


class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> MemoryItem: ...
    def get(self, memory_id: str) -> MemoryItem | None: ...
    def find_by_idempotency_key(self, campaign_id: str, key: str) -> MemoryItem | None: ...
    def list_active(self, campaign_id: str) -> tuple[MemoryItem, ...]: ...
    def query(
        self,
        *,
        campaign_id: str,
        visibility: Iterable[Visibility] | None = None,
        owner_id: str | None = None,
        kinds: Iterable[MemoryKind] | None = None,
        subject_ids: Iterable[str] | None = None,
        include_inactive: bool = False,
    ) -> tuple[MemoryItem, ...]: ...
    def replace(self, item: MemoryItem) -> MemoryItem: ...


def stable_memory_id(campaign_id: str, idempotency_basis: str) -> str:
    digest = hashlib.sha256(f"{campaign_id}|{idempotency_basis}".encode("utf-8")).hexdigest()[:20]
    return f"mem_{digest}"


class InMemoryMemoryStore:
    def __init__(self, items: Iterable[MemoryItem] | None = None) -> None:
        self._items: dict[str, MemoryItem] = {item.memory_id: item for item in (items or [])}
        self._counter = itertools.count(1)

    def add(self, item: MemoryItem) -> MemoryItem:
        if item.memory_id in self._items:
            existing = self._items[item.memory_id]
            merged = replace(
                existing,
                source_turn_ids=tuple(dict.fromkeys([*existing.source_turn_ids, *item.source_turn_ids])),
                source_event_ids=tuple(dict.fromkeys([*existing.source_event_ids, *item.source_event_ids])),
                confirmed_state_change_ids=tuple(dict.fromkeys([*existing.confirmed_state_change_ids, *item.confirmed_state_change_ids])),
                salience=max(existing.salience, item.salience),
                confidence=max(existing.confidence, item.confidence),
                last_reinforced_turn=item.created_at_turn or existing.last_reinforced_turn,
            )
            self._items[item.memory_id] = merged
            return merged
        self._items[item.memory_id] = item
        return item

    def next_id(self, prefix: str = "mem") -> str:
        return f"{prefix}_{next(self._counter):06d}"

    def get(self, memory_id: str) -> MemoryItem | None:
        return self._items.get(memory_id)

    def find_by_idempotency_key(self, campaign_id: str, key: str) -> MemoryItem | None:
        for item in self._items.values():
            if item.campaign_id == campaign_id and item.idempotency_key == key and item.status == MemoryStatus.ACTIVE:
                return item
        return None

    def list_active(self, campaign_id: str) -> tuple[MemoryItem, ...]:
        return tuple(item for item in self._items.values() if item.campaign_id == campaign_id and item.status == MemoryStatus.ACTIVE)

    def query(
        self,
        *,
        campaign_id: str,
        visibility: Iterable[Visibility] | None = None,
        owner_id: str | None = None,
        kinds: Iterable[MemoryKind] | None = None,
        subject_ids: Iterable[str] | None = None,
        include_inactive: bool = False,
    ) -> tuple[MemoryItem, ...]:
        visibility_set = set(visibility) if visibility is not None else None
        kind_set = set(kinds) if kinds is not None else None
        subject_set = set(subject_ids) if subject_ids is not None else None
        result: list[MemoryItem] = []
        for item in self._items.values():
            if item.campaign_id != campaign_id:
                continue
            if not include_inactive and item.status != MemoryStatus.ACTIVE:
                continue
            if visibility_set is not None and item.visibility not in visibility_set:
                continue
            if owner_id is not None and item.owner_id != owner_id:
                continue
            if kind_set is not None and item.kind not in kind_set:
                continue
            if subject_set is not None and not subject_set.intersection(item.subject_ids):
                continue
            result.append(item)
        result.sort(key=lambda item: (item.salience, item.confidence, item.memory_id), reverse=True)
        return tuple(result)

    def replace(self, item: MemoryItem) -> MemoryItem:
        if item.memory_id not in self._items:
            raise KeyError(f"unknown memory_id: {item.memory_id}")
        self._items[item.memory_id] = item
        return item
