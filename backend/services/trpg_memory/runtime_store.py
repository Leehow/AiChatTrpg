"""Async SQLAlchemy bridge for runtime memory proposals.

The scaffold's ``MemoryCommitGate`` is intentionally storage-agnostic and
sync-friendly for unit tests. ChatRPG's live IC turn runs inside an
``AsyncSession``, so this module mirrors the gate semantics against ORM rows
while preserving the same dataclass result shape.

V3 changes duplicate handling: durable facts are reinforced instead of skipped.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, TRPGMemoryItem
from services.trpg_context.models import Visibility
from services.trpg_memory.memory_identity import (
    infer_identity_scope,
    stable_idempotency_key,
    stable_memory_id_from_key,
)
from services.trpg_memory.memory_models import (
    MemoryCommitResult,
    MemoryIdentityScope,
    MemoryItem,
    MemoryOperation,
    MemoryProposal,
    MemoryStatus,
    MemoryValidationIssue,
    source_evidence_from_json,
    source_evidence_to_json,
)
from services.trpg_memory.memory_public_view import PublicMemoryView, MemoryPublicViewService
from services.trpg_memory.proposal_validator import MemoryProposalValidator


async def commit_memory_proposals(
    db: AsyncSession,
    session: GameSession,
    proposals: Sequence[MemoryProposal],
    *,
    transcript_text: str,
    confirmed_state_change_ids: Iterable[str] = (),
    campaign_id: str | None = None,
    validator: MemoryProposalValidator | None = None,
) -> MemoryCommitResult:
    """Validate and persist proposals as ``TRPGMemoryItem`` rows.

    ``campaign_id`` defaults to the session id. That keeps this compatible
    with ChatRPG's current one-session-per-campaign data model while leaving
    room for a later campaign table.
    """

    cid = str(campaign_id or session.id)
    validator = validator or MemoryProposalValidator()
    committed: list[MemoryItem] = []
    reinforced: list[MemoryItem] = []
    rejected: list[MemoryValidationIssue] = []
    duplicates: list[MemoryProposal] = []

    for proposal in proposals:
        if proposal.operation == MemoryOperation.NOOP:
            duplicates.append(proposal)
            continue

        issues = validator.validate(
            proposal,
            transcript_text=transcript_text,
            confirmed_state_change_ids=confirmed_state_change_ids,
        )
        blocking = [issue for issue in issues if issue.severity == "error"]
        if blocking:
            rejected.extend(blocking)
            continue

        idempotency_key = proposal.idempotency_key or _idempotency_key(cid, proposal)
        existing = await _find_existing(db, session_id=session.id, key=idempotency_key)
        if existing is not None:
            if infer_identity_scope(proposal) == MemoryIdentityScope.DURABLE_FACT:
                reinforced.append(_reinforce_row(existing, proposal))
            else:
                duplicates.append(proposal)
            continue

        memory_id = stable_memory_id_from_key(cid, idempotency_key)
        item = MemoryItem.from_proposal(
            memory_id=memory_id,
            campaign_id=cid,
            proposal=proposal,
        )
        if item.idempotency_key is None:
            item = item.with_status(item.status, idempotency_key=idempotency_key)

        db.add(_row_from_item(item, session_id=session.id))
        committed.append(item)

    if committed or reinforced:
        await db.flush()

    return MemoryCommitResult(
        committed=tuple(committed),
        rejected=tuple(rejected),
        duplicate_noops=tuple(duplicates),
        reinforced=tuple(reinforced),
    )


async def list_session_memory_items(
    db: AsyncSession,
    session_id: str,
    *,
    visibility: Iterable[Visibility] | None = None,
    include_inactive: bool = False,
    limit: int = 100,
) -> list[MemoryItem]:
    """Load committed memory rows for service/debug projections."""

    stmt = select(TRPGMemoryItem).where(TRPGMemoryItem.session_id == session_id)
    if visibility is not None:
        stmt = stmt.where(TRPGMemoryItem.visibility.in_([v.value for v in visibility]))
    if not include_inactive:
        stmt = stmt.where(TRPGMemoryItem.status == MemoryStatus.ACTIVE.value)
    stmt = stmt.order_by(TRPGMemoryItem.created_at.desc()).limit(max(1, min(limit, 500)))
    rows = list((await db.execute(stmt)).scalars().all())
    return [_item_from_row(row) for row in rows]


async def build_public_memory_view(
    db: AsyncSession,
    session_id: str,
    *,
    limit: int = 300,
) -> PublicMemoryView:
    """Build a player-safe projection of committed session memories."""

    items = await list_session_memory_items(
        db,
        session_id,
        visibility=(Visibility.PUBLIC, Visibility.PARTY_KNOWN),
        include_inactive=False,
        limit=limit,
    )
    store = StaticMemoryStore(items)
    return MemoryPublicViewService(store).build_for_party(campaign_id=session_id)


def memory_item_to_dict(item: MemoryItem) -> dict[str, object]:
    return {
        "memory_id": item.memory_id,
        "campaign_id": item.campaign_id,
        "kind": item.kind.value,
        "text": item.text,
        "visibility": item.visibility.value,
        "owner_id": item.owner_id,
        "subject_ids": list(item.subject_ids),
        "source_turn_ids": list(item.source_turn_ids),
        "source_quote": item.source_quote,
        "source_quotes": source_evidence_to_json(item.source_quotes),
        "source_event_ids": list(item.source_event_ids),
        "confirmed_state_change_ids": list(item.confirmed_state_change_ids),
        "confidence": item.confidence,
        "salience": item.salience,
        "truth_status": item.truth_status.value,
        "status": item.status.value,
        "pin_policy": item.pin_policy.value,
        "identity_scope": item.identity_scope.value,
        "reinforcement_count": item.reinforcement_count,
        "supersedes_memory_id": item.supersedes_memory_id,
        "superseded_by": item.superseded_by,
        "invalidated_by_turn_id": item.invalidated_by_turn_id,
        "correction_reason": item.correction_reason,
        "idempotency_key": item.idempotency_key,
        "created_at_turn": item.created_at_turn,
        "last_reinforced_turn": item.last_reinforced_turn,
        "tags": list(item.tags),
        "metadata": dict(item.metadata),
    }


def public_memory_view_to_dict(view: PublicMemoryView) -> dict[str, object]:
    return {
        "relationships": [
            {
                "npc_id": item.npc_id,
                "summary": item.summary,
                "confidence": item.confidence,
                "known_reasons": list(item.known_reasons),
            }
            for item in view.relationships
        ],
        "clues": [
            {
                "clue_id": item.clue_id,
                "title": item.title,
                "status": item.status,
                "points_to": list(item.points_to),
                "summary": item.summary,
            }
            for item in view.clues
        ],
        "open_threads": list(view.open_threads),
        "remembered_facts": list(view.remembered_facts),
    }


class StaticMemoryStore:
    """Tiny MemoryStore-compatible adapter for projection services."""

    def __init__(self, items: Iterable[MemoryItem]) -> None:
        self._items = tuple(items)

    def add(self, item: MemoryItem) -> MemoryItem:
        raise NotImplementedError

    def get(self, memory_id: str) -> MemoryItem | None:
        return next((item for item in self._items if item.memory_id == memory_id), None)

    def find_by_idempotency_key(self, campaign_id: str, key: str) -> MemoryItem | None:
        return next(
            (
                item for item in self._items
                if item.campaign_id == campaign_id and item.idempotency_key == key
            ),
            None,
        )

    def list_active(self, campaign_id: str) -> tuple[MemoryItem, ...]:
        return tuple(
            item for item in self._items
            if item.campaign_id == campaign_id and item.status == MemoryStatus.ACTIVE
        )

    def query(
        self,
        *,
        campaign_id: str,
        visibility: Iterable[Visibility] | None = None,
        owner_id: str | None = None,
        kinds: Iterable[Any] | None = None,
        subject_ids: Iterable[str] | None = None,
        include_inactive: bool = False,
    ) -> tuple[MemoryItem, ...]:
        visibility_set = set(visibility) if visibility is not None else None
        kind_set = set(kinds) if kinds is not None else None
        subject_set = set(subject_ids) if subject_ids is not None else None
        out: list[MemoryItem] = []
        for item in self._items:
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
            out.append(item)
        return tuple(out)

    def replace(self, item: MemoryItem) -> MemoryItem:
        raise NotImplementedError


_StaticMemoryStore = StaticMemoryStore


async def _find_existing(
    db: AsyncSession,
    *,
    session_id: str,
    key: str,
) -> TRPGMemoryItem | None:
    stmt = (
        select(TRPGMemoryItem)
        .where(TRPGMemoryItem.session_id == session_id)
        .where(TRPGMemoryItem.idempotency_key == key)
        .where(TRPGMemoryItem.status == MemoryStatus.ACTIVE.value)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _idempotency_key(campaign_id: str, proposal: MemoryProposal) -> str:
    return stable_idempotency_key(campaign_id, proposal)


def _row_from_item(item: MemoryItem, *, session_id: str) -> TRPGMemoryItem:
    return TRPGMemoryItem(
        memory_id=item.memory_id,
        session_id=session_id,
        campaign_id=item.campaign_id,
        kind=item.kind.value,
        text=item.text,
        visibility=item.visibility.value,
        owner_id=item.owner_id or "",
        subject_ids_json=list(item.subject_ids),
        source_turn_ids_json=list(item.source_turn_ids),
        source_event_ids_json=list(item.source_event_ids),
        source_quotes_json=source_evidence_to_json(item.source_quotes),
        confirmed_state_change_ids_json=list(item.confirmed_state_change_ids),
        identity_scope=item.identity_scope.value,
        reinforcement_count=int(item.reinforcement_count or 0),
        confidence=float(item.confidence),
        salience=float(item.salience),
        truth_status=item.truth_status.value,
        status=item.status.value,
        pin_policy=item.pin_policy.value,
        supersedes_memory_id=item.supersedes_memory_id or "",
        superseded_by=item.superseded_by or "",
        invalidated_by_turn_id=item.invalidated_by_turn_id or "",
        correction_reason=item.correction_reason or "",
        idempotency_key=item.idempotency_key or "",
        created_at_turn=item.created_at_turn or "",
        last_reinforced_turn=item.last_reinforced_turn or "",
        tags_json=list(item.tags),
        metadata_json=dict(item.metadata),
    )


def _item_from_row(row: TRPGMemoryItem) -> MemoryItem:
    from services.trpg_memory.memory_models import MemoryKind, PinPolicy, TruthStatus

    identity_scope_raw = getattr(row, "identity_scope", None) or MemoryIdentityScope.DURABLE_FACT.value
    try:
        identity_scope = MemoryIdentityScope(identity_scope_raw)
    except ValueError:
        identity_scope = MemoryIdentityScope.DURABLE_FACT

    source_quotes = source_evidence_from_json(getattr(row, "source_quotes_json", None) or [])
    source_quote = source_quotes[0].text if source_quotes else None

    return MemoryItem(
        memory_id=row.memory_id,
        campaign_id=row.campaign_id,
        kind=MemoryKind(row.kind),
        text=row.text,
        visibility=Visibility(row.visibility),
        owner_id=row.owner_id or None,
        subject_ids=tuple(str(x) for x in (row.subject_ids_json or [])),
        source_turn_ids=tuple(str(x) for x in (row.source_turn_ids_json or [])),
        source_quote=source_quote,
        source_quotes=source_quotes,
        source_event_ids=tuple(str(x) for x in (row.source_event_ids_json or [])),
        confirmed_state_change_ids=tuple(str(x) for x in (row.confirmed_state_change_ids_json or [])),
        confidence=float(row.confidence),
        salience=float(row.salience),
        truth_status=TruthStatus(row.truth_status),
        status=MemoryStatus(row.status),
        pin_policy=PinPolicy(row.pin_policy),
        identity_scope=identity_scope,
        reinforcement_count=int(getattr(row, "reinforcement_count", 0) or 0),
        supersedes_memory_id=row.supersedes_memory_id or None,
        superseded_by=row.superseded_by or None,
        invalidated_by_turn_id=row.invalidated_by_turn_id or None,
        correction_reason=row.correction_reason or None,
        idempotency_key=row.idempotency_key or None,
        created_at_turn=row.created_at_turn or None,
        last_reinforced_turn=row.last_reinforced_turn or None,
        tags=tuple(str(x) for x in (row.tags_json or [])),
        metadata=row.metadata_json or {},
    )


def _reinforce_row(row: TRPGMemoryItem, proposal: MemoryProposal) -> MemoryItem:
    metadata = dict(row.metadata_json or {})
    count = int(getattr(row, "reinforcement_count", 0) or metadata.get("reinforcement_count") or 0) + 1
    source_turn = proposal.source_turn_ids[-1] if proposal.source_turn_ids else (row.last_reinforced_turn or row.created_at_turn or "")

    row.source_turn_ids_json = _union(row.source_turn_ids_json or [], proposal.source_turn_ids)
    row.source_event_ids_json = _union(row.source_event_ids_json or [], proposal.source_event_ids)
    row.confirmed_state_change_ids_json = _union(row.confirmed_state_change_ids_json or [], proposal.confirmed_state_change_ids)
    row.source_quotes_json = _union_evidence(getattr(row, "source_quotes_json", None) or [], source_evidence_to_json(proposal.source_quotes))
    row.tags_json = _union(row.tags_json or [], proposal.tags)
    row.confidence = max(float(row.confidence or 0), float(proposal.confidence or 0))
    row.salience = min(1.0, max(float(row.salience or 0), float(proposal.salience or 0)) + 0.03)
    row.last_reinforced_turn = source_turn
    row.reinforcement_count = count
    metadata.update({
        "reinforcement_count": count,
        "last_reinforced_turn": source_turn,
        "last_reinforced_proposal_text": proposal.text[:500],
    })
    row.metadata_json = metadata
    return _item_from_row(row)


def _union(existing: Iterable[Any], incoming: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*list(existing or []), *list(incoming or [])]:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _union_evidence(existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in [*list(existing or []), *list(incoming or [])]:
        if not isinstance(value, dict):
            continue
        text = str(value.get("text") or "").strip()
        role = str(value.get("role") or "")
        key = (role, text.casefold())
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(dict(value))
    return out[-20:]
