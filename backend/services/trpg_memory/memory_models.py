"""Memory models for TRPG runtime post-processing.

The key rule in this module: a memory item is not an informal summary.
It is a versioned, source-backed object that carries visibility, owner,
truth-status, lifecycle metadata, and evidence spans.

V3 adds two important distinctions:

* Evidence is per proposal, not a shared turn-level quote.
* Idempotency has two scopes: event memories can be turn-scoped, while
  durable facts / clues / relationships are reinforced across turns.

These dataclasses deliberately avoid Pydantic so this scaffold can be
introduced into FastAPI projects that may be on either Pydantic v1 or v2.
API DTOs can wrap these models later.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from services.trpg_context.models import Visibility


class MemoryKind(str, Enum):
    FACT = "fact"                    # objective world fact
    BELIEF = "belief"                # subjective belief; may be false
    RELATIONSHIP = "relationship"    # long-term social attitude
    EMOTION = "emotion"              # transient but recallable emotional residue
    PLOT = "plot"                    # unresolved thread / countdown / hook
    CLUE = "clue"                    # investigation clue ledger entry
    SECRET = "secret"                # GM-only or NPC-private secret
    RULE_NOTE = "rule_note"          # table ruling or rules note
    PLAYER_PREFERENCE = "player_preference"


class MemoryOperation(str, Enum):
    ADD = "add"
    UPDATE = "update"
    SUPERSEDE = "supersede"
    INVALIDATE = "invalidate"
    NOOP = "noop"


class TruthStatus(str, Enum):
    TRUE = "true"                    # accepted canonical fact
    FALSE = "false"                  # disproven/corrected
    UNVERIFIED = "unverified"        # plausible, not confirmed
    BELIEF = "belief"                # explicitly subjective
    RUMOR = "rumor"                  # hearsay
    GM_SECRET = "gm_secret"          # true in GM layer, hidden from player layer


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


class PinPolicy(str, Enum):
    NEVER = "never"
    DYNAMIC_RETRIEVAL_ONLY = "dynamic_retrieval_only"
    SCENE_PREFIX = "scene_prefix"
    SESSION_PREFIX = "session_prefix"
    CHAPTER_PREFIX = "chapter_prefix"
    CAMPAIGN_PREFIX = "campaign_prefix"
    GLOBAL_PREFIX = "global_prefix"


class EvidenceRole(str, Enum):
    PLAYER = "player"
    GM = "gm"
    SYSTEM = "system"
    STRUCTURED_EVENT = "structured_event"
    STATE_CHANGE = "state_change"


class MemoryIdentityScope(str, Enum):
    """How idempotency should treat repeated memories."""

    EVENT = "event"
    DURABLE_FACT = "durable_fact"


@dataclass(frozen=True)
class SourceEvidence:
    """A concrete span that supports one memory proposal."""

    text: str
    role: EvidenceRole
    source_turn_id: str | None = None
    source_event_id: str | None = None
    source_state_change_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "role": self.role.value,
            "source_turn_id": self.source_turn_id,
            "source_event_id": self.source_event_id,
            "source_state_change_id": self.source_state_change_id,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceEvidence":
        raw_role = str(value.get("role") or EvidenceRole.GM.value)
        try:
            role = EvidenceRole(raw_role)
        except ValueError:
            role = EvidenceRole.GM
        return cls(
            text=str(value.get("text") or ""),
            role=role,
            source_turn_id=_opt_str(value.get("source_turn_id")),
            source_event_id=_opt_str(value.get("source_event_id")),
            source_state_change_id=_opt_str(value.get("source_state_change_id")),
            start_offset=_opt_int(value.get("start_offset")),
            end_offset=_opt_int(value.get("end_offset")),
        )


@dataclass(frozen=True)
class MemoryProposal:
    """Candidate memory emitted by the memory extractor.

    The extractor should propose memories; it should not write directly.
    MemoryCommitGate validates these proposals against the transcript,
    confirmed state changes, and visibility policy before committing.
    """

    operation: MemoryOperation
    kind: MemoryKind
    text: str
    visibility: Visibility
    owner_id: str | None
    subject_ids: tuple[str, ...]
    source_turn_ids: tuple[str, ...]
    source_quote: str | None = None
    source_quotes: tuple[SourceEvidence, ...] = field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)
    confirmed_state_change_ids: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.8
    salience: float = 0.5
    truth_status: TruthStatus = TruthStatus.UNVERIFIED
    pin_policy: PinPolicy = PinPolicy.DYNAMIC_RETRIEVAL_ONLY
    identity_scope: MemoryIdentityScope | None = None
    writes_world_state: bool = False
    world_state_patch: Mapping[str, Any] | None = None
    supersedes_memory_id: str | None = None
    idempotency_key: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def evidence_texts(self) -> tuple[str, ...]:
        texts = [ev.text.strip() for ev in self.source_quotes if ev.text and ev.text.strip()]
        if self.source_quote and self.source_quote.strip():
            texts.append(self.source_quote.strip())
        seen: set[str] = set()
        out: list[str] = []
        for text in texts:
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return tuple(out)

    def inferred_identity_scope(self) -> MemoryIdentityScope:
        if self.identity_scope is not None:
            return self.identity_scope
        if self.kind == MemoryKind.PLOT and "event" in set(self.tags):
            return MemoryIdentityScope.EVENT
        if self.kind in {MemoryKind.RULE_NOTE, MemoryKind.PLAYER_PREFERENCE}:
            return MemoryIdentityScope.DURABLE_FACT
        return MemoryIdentityScope.DURABLE_FACT

    def normalized_idempotency_basis(self) -> str:
        # Kept for backward compatibility. The actual implementation now lives
        # in memory_identity.py so stores can compute matching keys centrally.
        from services.trpg_memory.memory_identity import proposal_identity_basis

        return proposal_identity_basis(self)


@dataclass(frozen=True)
class MemoryItem:
    """Committed long-term memory object."""

    memory_id: str
    campaign_id: str
    kind: MemoryKind
    text: str
    visibility: Visibility
    owner_id: str | None
    subject_ids: tuple[str, ...]
    source_turn_ids: tuple[str, ...]
    source_quote: str | None = None
    source_quotes: tuple[SourceEvidence, ...] = field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)
    confirmed_state_change_ids: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.8
    salience: float = 0.5
    truth_status: TruthStatus = TruthStatus.UNVERIFIED
    status: MemoryStatus = MemoryStatus.ACTIVE
    pin_policy: PinPolicy = PinPolicy.DYNAMIC_RETRIEVAL_ONLY
    identity_scope: MemoryIdentityScope = MemoryIdentityScope.DURABLE_FACT
    reinforcement_count: int = 0
    supersedes_memory_id: str | None = None
    superseded_by: str | None = None
    invalidated_by_turn_id: str | None = None
    correction_reason: str | None = None
    idempotency_key: str | None = None
    created_at_turn: str | None = None
    last_reinforced_turn: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_proposal(cls, *, memory_id: str, campaign_id: str, proposal: MemoryProposal) -> "MemoryItem":
        source_quote = proposal.source_quote
        if not source_quote and proposal.source_quotes:
            source_quote = proposal.source_quotes[0].text
        return cls(
            memory_id=memory_id,
            campaign_id=campaign_id,
            kind=proposal.kind,
            text=proposal.text,
            visibility=proposal.visibility,
            owner_id=proposal.owner_id,
            subject_ids=proposal.subject_ids,
            source_turn_ids=proposal.source_turn_ids,
            source_quote=source_quote,
            source_quotes=proposal.source_quotes,
            source_event_ids=proposal.source_event_ids,
            confirmed_state_change_ids=proposal.confirmed_state_change_ids,
            confidence=proposal.confidence,
            salience=proposal.salience,
            truth_status=proposal.truth_status,
            pin_policy=proposal.pin_policy,
            identity_scope=proposal.inferred_identity_scope(),
            supersedes_memory_id=proposal.supersedes_memory_id,
            idempotency_key=proposal.idempotency_key,
            created_at_turn=proposal.source_turn_ids[-1] if proposal.source_turn_ids else None,
            tags=proposal.tags,
            metadata=proposal.metadata,
        )

    def with_status(self, status: MemoryStatus, **updates: Any) -> "MemoryItem":
        return replace(self, status=status, **updates)

    def with_updates(self, **updates: Any) -> "MemoryItem":
        return replace(self, **updates)


@dataclass(frozen=True)
class MemoryExtractionResult:
    proposals: Sequence[MemoryProposal]
    rejected_notes: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemoryValidationIssue:
    code: str
    message: str
    severity: str = "error"  # info | warning | error
    proposal: MemoryProposal | None = None


@dataclass(frozen=True)
class MemoryCommitResult:
    committed: tuple[MemoryItem, ...]
    rejected: tuple[MemoryValidationIssue, ...]
    duplicate_noops: tuple[MemoryProposal, ...] = field(default_factory=tuple)
    reinforced: tuple[MemoryItem, ...] = field(default_factory=tuple)


def source_evidence_from_json(values: Any) -> tuple[SourceEvidence, ...]:
    if not isinstance(values, list):
        return ()
    out: list[SourceEvidence] = []
    for item in values:
        if isinstance(item, Mapping):
            ev = SourceEvidence.from_dict(item)
            if ev.text.strip():
                out.append(ev)
    return tuple(out)


def source_evidence_to_json(values: Sequence[SourceEvidence]) -> list[dict[str, Any]]:
    return [ev.to_dict() for ev in values if ev.text and ev.text.strip()]


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _opt_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
