"""Prompt 4 — Detailed Rule Package Extraction Prompt."""

from __future__ import annotations

import json
from typing import Any, Dict

from .system import output_language_clause


PACKAGE_TASK = """Task: extract one detailed on-demand rule package as an addition to the thick resident core.

GOAL
Read the supplied source, the current resident core, and the package descriptor, then produce:
1. rule_packages/{PACKAGE_ID}.md

CORE + PACKAGE RELATION
This package is not a replacement for the resident core.
It is an incremental detail layer.

Assume the LLM GM already has:
- core_rules.md
- world_guide.md or style_guide.md

This package must therefore:
- avoid repeating the resident core at the same abstraction level
- add the material that remains operationally necessary beyond the resident core
- still be executable with only core_rules.md + this package

Do not require any other detailed package.

LINE NUMBER RULE
If the source includes line numbers, treat them as an internal focusing aid only.
Do not emit line numbers, span references, or source maps in the output.

RESIDENT_PRESENCE LOGIC
Interpret PACKAGE_DESCRIPTOR.resident_presence as follows:

If resident_presence = "kernel":
- the resident core already contains the ordinary-play kernel
- this package should focus on:
  - expanded procedures
  - rare branches
  - long exception chains
  - heavy tables
  - package-specific edge cases
  - optional/variant extensions
  - specialized cases that would bloat the core

If resident_presence = "none":
- the resident core does not meaningfully cover this subsystem
- this package should provide the full operational subsystem, while still keeping a brief prerequisite recap at the start

If resident_presence = "full":
- treat this as a narrow addendum only
- do not restate content already fully resident

BOUNDARY RULES
- Follow PACKAGE_DESCRIPTOR as the authoritative boundary.
- Extract only content whose best canonical home is this package.
- Keep small lists (10 items or fewer) or descriptive mini-tables in markdown when they are tightly tied to the package and not worth separate JSON.
- Do not inline giant catalogs of spells, items, or monsters here.
- Do not import long lore or world material.
- Preserve formulas, thresholds, sequences, prerequisites, exceptions, overrides, and edge conditions.

REQUIRED STRUCTURE
# {PACKAGE_ID}
## 1. Package Purpose and Boundary
## 2. Load When
## 3. What This Package Adds Beyond the Resident Core
## 4. Minimum Prerequisite Recap
## 5. Expanded Procedures
## 6. Rare Branches, Edge Cases, and Exception Chains
## 7. Heavy Tables and Long References Kept in Markdown
## 8. Optional and Variant Material

WRITING RULES
- Write executable rule text, not a chapter summary.
- Use numbered steps for procedures.
- Use simple tables only when they reduce ambiguity.
- Make triggers, procedures, outcomes, and exceptions explicit.
- When a branch matters, preserve branch order.
- When a formula matters, preserve the formula exactly as given by the source.
- When a package rule depends on a resident kernel, refer to the dependency briefly and concretely instead of re-explaining the whole kernel.

OUTPUT CONTRACT
Return only this file block:

<<<FILE:rule_packages/{PACKAGE_ID}.md>>>
...markdown...
<<<END_FILE>>>

QUALITY BAR
- The worst failure is repeating the resident core instead of adding detail.
- The second worst failure is omitting rare but important branches.
- The third worst failure is losing procedural order.
"""


def package_user_prompt(
    *,
    book_id: str,
    book_title: str,
    package_id: str,
    output_language: str | None,
    package_descriptor: Dict[str, Any],
    current_core_rules_md: str,
    source_excerpt: str,
    excerpt_is_narrowed: bool,
    extra_hint: str | None = None,
) -> str:
    task = PACKAGE_TASK.replace("{PACKAGE_ID}", package_id)
    descriptor_json = json.dumps(package_descriptor, ensure_ascii=False, indent=2)
    source_label = (
        "SOURCE (narrowed line-numbered excerpt)"
        if excerpt_is_narrowed
        else "SOURCE (full line-numbered)"
    )
    parts = [
        task,
        "",
        "INPUT METADATA",
        f"- BOOK_ID: {book_id}",
        f"- BOOK_TITLE: {book_title}",
        f"- PACKAGE_ID: {package_id}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        "",
        "PACKAGE DESCRIPTOR",
        descriptor_json,
        "",
        "CURRENT RESIDENT CORE",
        current_core_rules_md or "(empty)",
    ]
    hint = (extra_hint or "").strip()
    if hint:
        parts += ["", "ADMIN EXTRA HINT", hint]
    parts += ["", source_label, source_excerpt]
    return "\n".join(parts)
