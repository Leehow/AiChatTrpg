"""Prompt 7 — Final Manifest Assembly Prompt.

v6 note: the final manifest assembly is usually a pure reducer (no
LLM needed) because the discovery manifest already contains most
fields. We keep the prompt here for the optional LLM-assisted
polish path, but pipeline.py assembles the final manifest in code
by default.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .system import output_language_clause


FINAL_TASK = """Task: compact and finalize the merged manifest for the compiled rulebook.

GOAL
Produce one final merged manifest:
1. knowledge_manifest.json

MANIFEST GOALS
- keep the structure compact
- keep it machine-usable
- avoid bloated commentary
- include only the fields needed for runtime loading and lookup
- do not create additional index files

FINALIZATION RULES
- Preserve the resident section.
- Keep only detailed packages that actually exist.
- Keep only parameter families that actually exist.
- Confirm the character sheet package fields and file paths.
- Keep aliases conservative and minimal.
- If an alias is ambiguous, omit it instead of guessing.
- Do not add line-number references.
- Do not add audit fields.
- Output must be strictly valid JSON.

OUTPUT CONTRACT
Return only this file block:

<<<FILE:knowledge_manifest.json>>>
{
  "book_id": "{BOOK_ID}",
  "book_title": "{BOOK_TITLE}",
  "world_mode": "",
  "resident": {
    "core_file": "core_rules.md",
    "companion_file": ""
  },
  "detailed_rule_packages": [],
  "parameter_families": [],
  "character_sheet_package": {
    "present": true,
    "template_file": "character_sheet/character_sheet_template.json",
    "guide_file": "character_sheet/character_creation_guide.md"
  },
  "aliases": []
}
<<<END_FILE>>>

QUALITY BAR
- The manifest must stay small and useful.
- Do not turn it into a documentation dump.
- The goal is loading and lookup, not prose completeness.
"""


def final_user_prompt(
    *,
    book_id: str,
    book_title: str,
    output_language: str | None,
    discovery_manifest: Dict[str, Any],
    existing_packages: list,
    existing_families: list,
    character_sheet_present: bool,
) -> str:
    parts = [
        FINAL_TASK.replace("{BOOK_ID}", book_id).replace("{BOOK_TITLE}", book_title),
        "",
        "INPUT METADATA",
        f"- BOOK_ID: {book_id}",
        f"- BOOK_TITLE: {book_title}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        "",
        "DISCOVERY MANIFEST DRAFT",
        json.dumps(discovery_manifest, ensure_ascii=False, indent=2),
        "",
        "EXTANT PACKAGE IDS",
        json.dumps(existing_packages, ensure_ascii=False),
        "",
        "EXTANT FAMILY IDS",
        json.dumps(existing_families, ensure_ascii=False),
        "",
        f"CHARACTER_SHEET_PRESENT: {str(bool(character_sheet_present)).lower()}",
    ]
    return "\n".join(parts)
