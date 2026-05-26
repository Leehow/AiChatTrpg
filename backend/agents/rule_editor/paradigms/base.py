"""Paradigm base types — shared by scenario / family / character_sheet."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> "ValidationResult":
        return cls(ok=True, warnings=warnings or [])

    @classmethod
    def fail(cls, errors: list[str]) -> "ValidationResult":
        return cls(ok=False, errors=errors)


ParadigmValidator = Callable[[Any], ValidationResult]


@dataclass(frozen=True)
class ScenarioParadigm:
    """One rule_package paradigm. Produces markdown content."""
    id: str
    description: str
    prompt_focus: str
    suggested_sections: tuple[str, ...] = ()

    def prompt_fragment(self, brief: str, current_content: str) -> str:
        sections = (
            "Suggested sections: " + ", ".join(self.suggested_sections) + "."
            if self.suggested_sections else ""
        )
        existing = (
            f"\n\nExisting content (rewrite or extend):\n{current_content}"
            if current_content.strip() else ""
        )
        return (
            f"# Designing the `{self.id}` rule package\n"
            f"{self.prompt_focus}\n"
            f"{sections}\n\n"
            f"User brief: {brief or '(none — design from scratch)'}"
            f"{existing}\n\n"
            "Output: a single Markdown blob, no code fences. Aim for "
            "300-1500 words. Prefer concise rule statements over fluff. "
            "Use Markdown headings (##, ###) for structure."
        )

    def validate(self, content: str) -> ValidationResult:
        if not isinstance(content, str) or not content.strip():
            return ValidationResult.fail(["empty content"])
        if len(content) < 50:
            return ValidationResult.fail(
                ["content too short (<50 chars); needs more substance"],
            )
        return ValidationResult.success()


@dataclass(frozen=True)
class FamilyParadigm:
    """One parameter_family paradigm. Produces a list of structured entries."""
    id: str
    description: str
    entry_definition: str
    family_specific_fields: tuple[str, ...] = ()

    def prompt_fragment(self, brief: str, current_entries: list[dict]) -> str:
        fields = (
            f"Family-specific fields: {', '.join(self.family_specific_fields)}."
            if self.family_specific_fields
            else "Family-specific fields: (none — common shell only)."
        )
        existing = ""
        if current_entries:
            existing = (
                f"\n\nExisting entries ({len(current_entries)}): "
                + ", ".join(
                    str(e.get("name") or e.get("id") or "")
                    for e in current_entries[:8]
                )
                + ("…" if len(current_entries) > 8 else "")
            )
        return (
            f"# Designing the `{self.id}` parameter family\n"
            f"Each entry is: {self.entry_definition}\n\n"
            f"Common shell (every entry):\n"
            "  id (BOOK_ID.FAMILY_ID.NNN — leave blank, will be assigned), "
            "name, aliases[], family, summary, tags[], rule_context.\n"
            f"{fields}\n\n"
            f"User brief: {brief or '(none — design a starter set)'}"
            f"{existing}\n\n"
            "Output: JSON object {\"entries\": [...]} where each entry is "
            "an object with the common shell + family-specific fields. "
            "Aim for 5-20 entries unless the brief asks otherwise. "
            "Tags are short snake_case; aliases are alternate names."
        )

    def validate(self, payload: dict | list) -> ValidationResult:
        entries = (
            payload.get("entries") if isinstance(payload, dict) else payload
        )
        if not isinstance(entries, list) or not entries:
            return ValidationResult.fail(["expected non-empty entries list"])
        errors: list[str] = []
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                errors.append(f"entries[{i}]: not an object")
                continue
            if not isinstance(e.get("name"), str) or not e.get("name").strip():
                errors.append(f"entries[{i}]: missing or empty `name`")
            if not isinstance(e.get("summary"), str):
                errors.append(f"entries[{i}]: missing `summary`")
        if errors:
            return ValidationResult.fail(errors[:10])
        return ValidationResult.success()
