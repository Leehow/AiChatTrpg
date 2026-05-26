"""Paradigm registry for the rule editor agent.

The catalog of paradigms is sourced from the V6 rule parser
(prompts/discovery.py) so the editor and the parser agree on what counts
as a known paradigm. Every paradigm exposes:

- `id`: canonical snake_case id (or the special `"custom"`).
- `description`: one-line summary used in the system prompt catalog.
- `prompt_fragment(brief, current_state)`: text appended to the LLM call
  when a `design_*` tool with this paradigm is invoked. The fragment
  carries paradigm-specific guidance (focus, structure, common pitfalls).
- `validate(payload)`: post-LLM-output sanity check; returns a
  ValidationResult. The agent gets structured feedback on failure.

Importing this package gets you `lookup_scenario`, `lookup_family`,
`character_sheet`, and the catalog rendering helpers used by `prompts.py`.

Design: docs/design/2026-05-01-rule-editor-agent.md §6.5, §7.5
"""

from __future__ import annotations

from .base import (  # noqa: F401
    FamilyParadigm,
    ParadigmValidator,
    ScenarioParadigm,
    ValidationResult,
)
from .character_sheet import CHARACTER_SHEET_PARADIGM
from .families import FAMILY_PARADIGMS, FAMILY_PARADIGM_IDS, lookup_family
from .scenarios import (
    SCENARIO_PARADIGMS,
    SCENARIO_PARADIGM_IDS,
    lookup_scenario,
)


def render_catalog_markdown() -> str:
    """Compact catalog suitable for inclusion in the agent system prompt."""
    lines: list[str] = []
    lines.append("## Scenario paradigms (rule_packages)")
    for p in SCENARIO_PARADIGMS:
        lines.append(f"- `{p.id}` — {p.description}")
    lines.append("")
    lines.append("## Parameter family paradigms")
    for p in FAMILY_PARADIGMS:
        fields = ", ".join(p.family_specific_fields) or "(common shell only)"
        lines.append(f"- `{p.id}` — {p.description}; fields: {fields}")
    lines.append("")
    lines.append(
        "Use `custom` (with snake_case id) only if no canonical paradigm fits."
    )
    return "\n".join(lines)


__all__ = [
    "CHARACTER_SHEET_PARADIGM",
    "FAMILY_PARADIGMS",
    "FAMILY_PARADIGM_IDS",
    "FamilyParadigm",
    "ParadigmValidator",
    "SCENARIO_PARADIGMS",
    "SCENARIO_PARADIGM_IDS",
    "ScenarioParadigm",
    "ValidationResult",
    "lookup_family",
    "lookup_scenario",
    "render_catalog_markdown",
]
