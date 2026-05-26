"""Forbidden content guard for NPC planner cards and action proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .common import get_value, set_value, to_plain_data


TEXT_FIELDS_TO_SCAN = (
    "speech",
    "intent",
    "speech_intent",
    "player_facing_text",
    "suggested_player_facing",
    "emote",
    "gm_notes",
    "motivation",
    "summary",
    "beat",
)

HIGH_RISK_ACTION_TYPES = {
    "REVEAL_SECRET",
    "REVEAL_CORE_SECRET",
    "REVEAL_CLUE",
    "ALTER_WORLD_STATE",
}


@dataclass(frozen=True, slots=True)
class ForbiddenFact:
    fact_id: str
    label: str | None = None
    redaction_terms: tuple[str, ...] = ()
    severity: str = "high"  # low | medium | high | critical


@dataclass(slots=True)
class ForbiddenContentViolation:
    fact_id: str
    term: str
    field_path: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "fact_id": self.fact_id,
            "term": self.term,
            "field_path": self.field_path,
            "severity": self.severity,
        }


@dataclass(slots=True)
class SecretGuardDecision:
    decision: str  # allow | transform | block
    action: Any
    violations: list[ForbiddenContentViolation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "violations": [v.to_dict() for v in self.violations],
            "notes": list(self.notes),
            "action": to_plain_data(self.action),
        }


class ForbiddenContentGuard:
    """Detect and transform planner text that contains forbidden secrets.

    Fact-id filtering is necessary but insufficient: an LLM planner may put a
    protected fact directly in ``speech_intent`` or ``gm_notes``.  This guard
    scans text fields for configured redaction terms and blocks or transforms
    risky actions before they reach the main scene prompt.
    """

    def __init__(self, forbidden_facts: Iterable[ForbiddenFact] | None = None) -> None:
        self.forbidden_facts = list(forbidden_facts or [])
        self._compiled: list[tuple[ForbiddenFact, str, re.Pattern[str]]] = []
        for fact in self.forbidden_facts:
            terms = set(fact.redaction_terms)
            if fact.label:
                terms.add(fact.label)
            # Avoid scanning bare fact IDs like secret_core unless they may appear
            # literally in planner fields.  They are still useful for diagnostics.
            for term in terms:
                clean = str(term).strip()
                if not clean or len(clean) < 2:
                    continue
                pattern = re.compile(re.escape(clean), flags=re.IGNORECASE)
                self._compiled.append((fact, clean, pattern))

    @classmethod
    def from_fact_maps(
        cls,
        forbidden_fact_ids: Iterable[str] | None = None,
        redaction_terms_by_fact_id: dict[str, Iterable[str]] | None = None,
        labels_by_fact_id: dict[str, str] | None = None,
    ) -> "ForbiddenContentGuard":
        facts: list[ForbiddenFact] = []
        for fact_id in forbidden_fact_ids or []:
            facts.append(
                ForbiddenFact(
                    fact_id=str(fact_id),
                    label=(labels_by_fact_id or {}).get(str(fact_id)),
                    redaction_terms=tuple(str(v) for v in (redaction_terms_by_fact_id or {}).get(str(fact_id), [])),
                )
            )
        return cls(facts)

    def _scan_value(self, value: Any, path: str, violations: list[ForbiddenContentViolation]) -> None:
        if value is None:
            return
        if isinstance(value, str):
            for fact, term, pattern in self._compiled:
                if pattern.search(value):
                    violations.append(
                        ForbiddenContentViolation(
                            fact_id=fact.fact_id,
                            term=term,
                            field_path=path,
                            severity=fact.severity,
                        )
                    )
            return
        if isinstance(value, dict):
            for key, child in value.items():
                self._scan_value(child, f"{path}.{key}", violations)
            return
        if isinstance(value, list):
            for idx, child in enumerate(value):
                self._scan_value(child, f"{path}[{idx}]", violations)
            return

    def scan_action(self, action: Any) -> list[ForbiddenContentViolation]:
        violations: list[ForbiddenContentViolation] = []
        for field_name in TEXT_FIELDS_TO_SCAN:
            value = get_value(action, field_name)
            if value is None:
                continue
            self._scan_value(value, field_name, violations)
        return violations

    def sanitize_action(self, action: Any) -> SecretGuardDecision:
        violations = self.scan_action(action)
        if not violations:
            return SecretGuardDecision(decision="allow", action=action)

        action_type = str(get_value(action, "action_type", "")).upper()
        severities = {v.severity for v in violations}
        if action_type in HIGH_RISK_ACTION_TYPES or "critical" in severities:
            return SecretGuardDecision(
                decision="block",
                action=action,
                violations=violations,
                notes=["Blocked because the action text contains forbidden secret terms."],
            )

        sanitized = to_plain_data(action)
        if not isinstance(sanitized, dict):
            return SecretGuardDecision(
                decision="block",
                action=action,
                violations=violations,
                notes=["Blocked because action could not be safely transformed."],
            )

        for field_name in TEXT_FIELDS_TO_SCAN:
            if field_name not in sanitized:
                continue
            sanitized[field_name] = self._redact_value(sanitized[field_name])

        sanitized.setdefault("guardrails", {})
        sanitized["guardrails"]["secret_guard"] = {
            "decision": "transform",
            "blocked_fact_ids": sorted({v.fact_id for v in violations}),
            "instruction": "Render only a vague hint; do not include protected names, locations or identities.",
        }
        return SecretGuardDecision(
            decision="transform",
            action=sanitized,
            violations=violations,
            notes=["Transformed forbidden text into a vague hint instruction."],
        )

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            redacted = value
            for _, term, pattern in self._compiled:
                redacted = pattern.sub("[受保护秘密]", redacted)
            return redacted
        if isinstance(value, dict):
            return {k: self._redact_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(v) for v in value]
        return value
