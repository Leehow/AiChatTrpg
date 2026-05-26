"""Trace records for debugging AI-run TRPG turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class TurnTrace:
    turn_id: str
    campaign_id: str
    player_input: str
    context_cache_key: str | None = None
    context_prefix_hash: str | None = None
    retrieved_context_block_ids: tuple[str, ...] = field(default_factory=tuple)
    visibility_signature: str | None = None
    model_raw_output: Mapping[str, Any] | str | None = None
    parsed_contract_summary: Mapping[str, Any] = field(default_factory=dict)
    state_change_ids: tuple[str, ...] = field(default_factory=tuple)
    memory_proposal_count: int = 0
    committed_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    rejected_memory_count: int = 0
    audit_warnings: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    cache_metrics: Mapping[str, Any] = field(default_factory=dict)


class TurnTraceStore(Protocol):
    def save(self, trace: TurnTrace) -> TurnTrace: ...
    def get(self, turn_id: str) -> TurnTrace | None: ...


class InMemoryTurnTraceStore:
    def __init__(self) -> None:
        self._traces: dict[str, TurnTrace] = {}

    def save(self, trace: TurnTrace) -> TurnTrace:
        self._traces[trace.turn_id] = trace
        return trace

    def get(self, turn_id: str) -> TurnTrace | None:
        return self._traces.get(turn_id)
