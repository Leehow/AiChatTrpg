"""Character sheet paradigm — single, with suggested top-level structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import ValidationResult


SUGGESTED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "identity", "origin", "attributes", "modifiers", "derived_values",
    "resources", "classes_roles", "skills", "feats_features",
    "abilities_spells", "languages", "equipment",
    "currency_and_progression", "statuses", "notes",
)


@dataclass(frozen=True)
class CharacterSheetParadigm:
    id: str = "character_sheet"
    description: str = (
        "the character sheet template + creation guide"
    )
    suggested_keys: tuple[str, ...] = field(
        default_factory=lambda: SUGGESTED_TOP_LEVEL_KEYS,
    )

    def prompt_fragment(
        self, brief: str, current_template: dict | None,
    ) -> str:
        keys_hint = ", ".join(self.suggested_keys)
        existing = ""
        if isinstance(current_template, dict) and current_template:
            existing = (
                f"\n\nExisting template top-level keys: "
                f"{', '.join(sorted(current_template.keys()))}"
            )
        return (
            "# Designing the character sheet\n"
            "Output two parts:\n"
            "  1. `template_json` — a JSON object describing the sheet "
            "structure. Suggested top-level keys (use what fits, drop "
            "what doesn't):\n"
            f"     {keys_hint}\n\n"
            "  ## Canonical field shape (CRITICAL)\n"
            "  This template doubles as the schema for the generated "
            "character card. Use ONLY these field names so the runtime "
            "can resolve them:\n\n"
            "  • Numeric attributes (STR/CON/SIZ/...) → "
            "`{\"value\": <int>}`. **Never** use `default`, `base`, "
            "`score`, or `current` for the runtime number — only "
            "`value`. Optional sibling fields: `half`, `fifth` "
            "(filled by mechanical seed at character creation).\n\n"
            "  • Skills array → "
            "`[{\"name\": \"侦查\", \"base\": 25, \"value\": 25}, ...]`. "
            "`base` is the rules-baseline; `value` is what the "
            "character ends up with after occupation/interest "
            "allocation. List ONLY the skills the rules acknowledge — "
            "do not pad with hallucinated skills.\n\n"
            "  • Equipment / weapons → "
            "`{\"weapons\": [], \"items\": []}` (empty arrays at "
            "template time; the character creator fills them per "
            "occupation/era).\n\n"
            "  • Free text fields (background, identity strings) → "
            "`null` or `\"\"` so the LLM knows it's blank.\n\n"
            "  Anything not listed in this template is OFF-LIMITS for "
            "character generation; no extra skills, weapons, or "
            "fields will be added later.\n\n"
            "  2. `guide_content` — Markdown procedural text for "
            "creating a character: stat generation steps, point-buy or "
            "rolling, picking skills, gear, etc.\n\n"
            f"User brief: {brief or '(none — design from scratch)'}"
            f"{existing}"
        )

    def validate(
        self,
        template_json: dict | None,
        guide_content: str | None = None,
    ) -> ValidationResult:
        if not isinstance(template_json, dict) or not template_json:
            return ValidationResult.fail(["template_json must be a non-empty object"])
        warnings: list[str] = []
        present = set(template_json.keys())
        critical = {"identity", "attributes", "skills"}
        missing = critical - present
        if missing:
            warnings.append(
                f"missing common keys: {sorted(missing)} — ok if intentional",
            )
        # Detect the most common authoring mistake: attributes shaped as
        # {STR: {default: 50}} instead of {STR: {value: 50}}. The
        # character_ui compiler picks `value` as the canonical field;
        # `default`-shaped templates render as empty stat boxes at
        # runtime. We warn rather than reject so existing drafts keep
        # working, but the rule editor agent should auto-correct.
        attrs = template_json.get("attributes")
        if isinstance(attrs, dict) and attrs:
            bad = [
                k for k, v in attrs.items()
                if isinstance(v, dict)
                and "value" not in v
                and ("default" in v or "base" in v or "score" in v)
            ]
            if bad:
                warnings.append(
                    "attributes use non-canonical key for the number "
                    f"({sorted(bad)[:3]}…). Use `value` so runtime renders.",
                )
        if guide_content is not None:
            if not isinstance(guide_content, str):
                return ValidationResult.fail(["guide_content must be a string"])
            if guide_content.strip() and len(guide_content) < 30:
                warnings.append("guide_content is very short")
        return ValidationResult.success(warnings=warnings)


CHARACTER_SHEET_PARADIGM = CharacterSheetParadigm()
