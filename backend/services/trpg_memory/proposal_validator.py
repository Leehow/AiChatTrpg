"""Validation utilities for memory proposals.

The validator is intentionally conservative: it rejects direct DB writes from
unproven narration and asks the caller to link proposals to source turns,
evidence spans, or confirmed state changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from services.trpg_context.models import Visibility
from .evidence import evidence_overlap
from .memory_models import (
    EvidenceRole,
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    MemoryValidationIssue,
    TruthStatus,
)


@dataclass(frozen=True)
class ValidationConfig:
    min_confidence: float = 0.35
    require_source_turn: bool = True
    require_quote_or_state_change: bool = True
    fact_requires_confirmation: bool = True
    allow_gm_secret_without_quote: bool = True
    min_evidence_overlap_warning: float = 0.08
    min_clue_evidence_overlap: float = 0.12


class MemoryProposalValidator:
    def __init__(self, config: ValidationConfig | None = None) -> None:
        self.config = config or ValidationConfig()

    def validate(
        self,
        proposal: MemoryProposal,
        *,
        transcript_text: str = "",
        confirmed_state_change_ids: Iterable[str] = (),
    ) -> tuple[MemoryValidationIssue, ...]:
        issues: list[MemoryValidationIssue] = []
        confirmed_set = set(confirmed_state_change_ids)

        if proposal.operation == MemoryOperation.NOOP:
            return ()

        if not proposal.text.strip():
            issues.append(MemoryValidationIssue("empty_text", "memory text is empty", proposal=proposal))

        if self.config.require_source_turn and not proposal.source_turn_ids:
            issues.append(MemoryValidationIssue("missing_source_turn", "memory proposal must include source_turn_ids", proposal=proposal))

        if proposal.confidence < self.config.min_confidence:
            issues.append(
                MemoryValidationIssue(
                    "low_confidence",
                    f"confidence {proposal.confidence:.2f} below threshold {self.config.min_confidence:.2f}",
                    severity="warning",
                    proposal=proposal,
                )
            )

        if proposal.visibility == Visibility.NPC_PRIVATE and not proposal.owner_id:
            issues.append(MemoryValidationIssue("npc_private_without_owner", "npc_private memories require owner_id", proposal=proposal))

        if proposal.kind in {MemoryKind.BELIEF, MemoryKind.EMOTION, MemoryKind.RELATIONSHIP} and proposal.visibility == Visibility.PUBLIC:
            issues.append(
                MemoryValidationIssue(
                    "subjective_public_memory",
                    "subjective memories should normally be party_known or npc_private, not public",
                    severity="warning",
                    proposal=proposal,
                )
            )

        if proposal.kind in {MemoryKind.BELIEF, MemoryKind.EMOTION, MemoryKind.RELATIONSHIP}:
            if not proposal.owner_id and not proposal.subject_ids:
                issues.append(
                    MemoryValidationIssue(
                        "subjective_memory_without_actor",
                        "belief, emotion, and relationship memories require owner_id or subject_ids",
                        proposal=proposal,
                    )
                )

        linked_state_ids = set(proposal.confirmed_state_change_ids)
        has_confirmed_state = bool(linked_state_ids.intersection(confirmed_set))
        gm_secret_exemption = (
            self.config.allow_gm_secret_without_quote
            and proposal.visibility == Visibility.GM_ONLY
            and proposal.truth_status == TruthStatus.GM_SECRET
        )

        evidence_texts = proposal.evidence_texts()
        state_evidence = [
            ev for ev in proposal.source_quotes
            if ev.role == EvidenceRole.STATE_CHANGE and ev.source_state_change_id in confirmed_set
        ]
        structured_evidence = [
            ev for ev in proposal.source_quotes
            if ev.role == EvidenceRole.STRUCTURED_EVENT and ev.source_event_id
        ]
        has_quote = bool(evidence_texts)
        has_state_evidence = bool(state_evidence)
        has_structured_evidence = bool(structured_evidence)

        if (
            self.config.require_quote_or_state_change
            and not has_quote
            and not has_confirmed_state
            and not has_state_evidence
            and not has_structured_evidence
            and not gm_secret_exemption
        ):
            issues.append(
                MemoryValidationIssue(
                    "missing_source_quote_or_state_change",
                    "proposal needs source evidence, structured-event evidence, or a confirmed_state_change_id",
                    proposal=proposal,
                )
            )

        best_overlap: float | None = None
        transcript_quote_missing = False
        if has_quote and transcript_text:
            normalized_transcript = transcript_text.casefold()
            transcript_quotes = [
                ev.text.strip()
                for ev in proposal.source_quotes
                if ev.text.strip() and ev.role in {EvidenceRole.PLAYER, EvidenceRole.GM, EvidenceRole.SYSTEM}
            ]
            if proposal.source_quote and proposal.source_quote.strip() and not has_structured_evidence and not has_state_evidence:
                legacy = proposal.source_quote.strip()
                if legacy.casefold() not in {q.casefold() for q in transcript_quotes}:
                    transcript_quotes.append(legacy)

            if transcript_quotes:
                found_any = any(q.casefold() in normalized_transcript for q in transcript_quotes)
                if not found_any:
                    transcript_quote_missing = True
                    issues.append(
                        MemoryValidationIssue(
                            "source_quote_not_in_transcript",
                            "no source evidence quote was found in the supplied transcript text",
                            proposal=proposal,
                        )
                    )
                else:
                    best_overlap = max(evidence_overlap(proposal.text, q) for q in transcript_quotes)
                    if best_overlap < self.config.min_evidence_overlap_warning:
                        severity = "error" if proposal.kind == MemoryKind.CLUE else "warning"
                        issues.append(
                            MemoryValidationIssue(
                                "clue_source_quote_low_overlap" if proposal.kind == MemoryKind.CLUE else "source_quote_low_overlap",
                                "source evidence is present but weakly overlaps memory text",
                                severity=severity,
                                proposal=proposal,
                            )
                        )

        if proposal.kind == MemoryKind.CLUE and not gm_secret_exemption:
            strong_clue_evidence = has_structured_evidence or has_state_evidence or has_confirmed_state
            if best_overlap is not None and best_overlap >= self.config.min_clue_evidence_overlap:
                strong_clue_evidence = True
            if not strong_clue_evidence and not transcript_quote_missing:
                issues.append(
                    MemoryValidationIssue(
                        "clue_without_strong_evidence",
                        "CLUE memories must be backed by a structured discovery event, state evidence, confirmed state change, or high-overlap transcript quote",
                        proposal=proposal,
                    )
                )

        if self.config.fact_requires_confirmation and proposal.kind == MemoryKind.FACT:
            if not has_confirmed_state and not has_state_evidence and not gm_secret_exemption:
                issues.append(
                    MemoryValidationIssue(
                        "fact_without_confirmed_state_change",
                        "FACT memories must be backed by a confirmed state change, state evidence, or marked as GM_SECRET",
                        proposal=proposal,
                    )
                )

        return tuple(issues)

    def validate_many(
        self,
        proposals: Sequence[MemoryProposal],
        *,
        transcript_text: str = "",
        confirmed_state_change_ids: Iterable[str] = (),
    ) -> tuple[MemoryValidationIssue, ...]:
        issues: list[MemoryValidationIssue] = []
        for proposal in proposals:
            issues.extend(
                self.validate(
                    proposal,
                    transcript_text=transcript_text,
                    confirmed_state_change_ids=confirmed_state_change_ids,
                )
            )
        return tuple(issues)
