"""Commit gate for memory proposals.

This is the transactional boundary between LLM output and durable memory.
Everything upstream is a proposal; only this gate creates MemoryItem objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .memory_identity import infer_identity_scope, stable_idempotency_key, stable_memory_id_from_key
from .memory_models import (
    MemoryCommitResult,
    MemoryIdentityScope,
    MemoryItem,
    MemoryOperation,
    MemoryProposal,
    MemoryValidationIssue,
)
from .memory_store import MemoryStore
from .proposal_validator import MemoryProposalValidator


@dataclass(frozen=True)
class CommitGateConfig:
    reject_warning_severity: bool = False
    deterministic_ids: bool = True


class MemoryCommitGate:
    def __init__(
        self,
        memory_store: MemoryStore,
        validator: MemoryProposalValidator | None = None,
        config: CommitGateConfig | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.validator = validator or MemoryProposalValidator()
        self.config = config or CommitGateConfig()

    def commit(
        self,
        *,
        campaign_id: str,
        proposals: Sequence[MemoryProposal],
        transcript_text: str,
        confirmed_state_change_ids: Iterable[str],
    ) -> MemoryCommitResult:
        committed: list[MemoryItem] = []
        reinforced: list[MemoryItem] = []
        rejected: list[MemoryValidationIssue] = []
        duplicates: list[MemoryProposal] = []

        for proposal in proposals:
            if proposal.operation == MemoryOperation.NOOP:
                duplicates.append(proposal)
                continue

            validation_issues = self.validator.validate(
                proposal,
                transcript_text=transcript_text,
                confirmed_state_change_ids=confirmed_state_change_ids,
            )
            blocking = [
                issue for issue in validation_issues
                if issue.severity == "error" or (self.config.reject_warning_severity and issue.severity == "warning")
            ]
            if blocking:
                rejected.extend(blocking)
                continue

            idempotency_key = proposal.idempotency_key or self._idempotency_key(campaign_id, proposal)
            existing = self.memory_store.find_by_idempotency_key(campaign_id, idempotency_key)
            if existing is not None:
                if infer_identity_scope(proposal) == MemoryIdentityScope.DURABLE_FACT:
                    reinforced.append(self.memory_store.replace(_reinforce_item(existing, proposal)))
                else:
                    duplicates.append(proposal)
                continue

            if self.config.deterministic_ids:
                memory_id = stable_memory_id_from_key(campaign_id, idempotency_key)
            else:
                memory_id = stable_memory_id_from_key(campaign_id, idempotency_key)

            item = MemoryItem.from_proposal(
                memory_id=memory_id,
                campaign_id=campaign_id,
                proposal=proposal,
            )
            # Ensure generated key is stored for future idempotency checks.
            if item.idempotency_key is None:
                item = item.with_status(item.status, idempotency_key=idempotency_key)

            saved = self.memory_store.add(item)
            committed.append(saved)

        return MemoryCommitResult(
            committed=tuple(committed),
            rejected=tuple(rejected),
            duplicate_noops=tuple(duplicates),
            reinforced=tuple(reinforced),
        )

    def _idempotency_key(self, campaign_id: str, proposal: MemoryProposal) -> str:
        return stable_idempotency_key(campaign_id, proposal)


def _reinforce_item(existing: MemoryItem, proposal: MemoryProposal) -> MemoryItem:
    source_turn = proposal.source_turn_ids[-1] if proposal.source_turn_ids else existing.last_reinforced_turn
    metadata = dict(existing.metadata)
    count = int(existing.reinforcement_count or metadata.get("reinforcement_count") or 0) + 1
    metadata.update({
        "reinforcement_count": count,
        "last_reinforced_turn": source_turn,
        "last_reinforced_proposal_text": proposal.text[:500],
    })
    return existing.with_updates(
        source_turn_ids=_union(existing.source_turn_ids, proposal.source_turn_ids),
        source_event_ids=_union(existing.source_event_ids, proposal.source_event_ids),
        confirmed_state_change_ids=_union(existing.confirmed_state_change_ids, proposal.confirmed_state_change_ids),
        source_quotes=_union_evidence(existing.source_quotes, proposal.source_quotes),
        salience=min(1.0, max(existing.salience, proposal.salience) + 0.03),
        confidence=max(existing.confidence, proposal.confidence),
        last_reinforced_turn=source_turn,
        reinforcement_count=count,
        tags=_union(existing.tags, proposal.tags),
        metadata=metadata,
    )


def _union(a: Iterable[str], b: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*list(a or ()), *list(b or ())]:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _union_evidence(a, b):
    out = []
    seen: set[tuple[str, str]] = set()
    for ev in [*list(a or ()), *list(b or ())]:
        key = (ev.role.value, ev.text.casefold())
        if not ev.text.strip() or key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return tuple(out[-20:])
