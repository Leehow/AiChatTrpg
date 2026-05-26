"""Prompt 3 — Unified Knowledge Manifest Discovery Prompt.

Extended beyond the v2.0 spec to require line_hints on every
discovered package / family / character-sheet descriptor. Those
hints drive Stage 4-6 narrow excerpt slicing in line_focus.py.
"""

from __future__ import annotations

from .system import output_language_clause


DISCOVERY_TASK = """Task: discover the full minimal runtime artifact plan and output a single merged manifest.

GOAL
Read the entire rulebook, the current resident core, and the current companion file, then produce:
1. knowledge_manifest.json

IMPORTANT DISCOVERY PHILOSOPHY
Because the resident core is intentionally thick, only create detailed packages for subsystems that still justify separate loading.

A detailed package should exist only when at least one of the following is true:
- it is too large to keep fully resident
- it contains long exception chains
- it is highly table-driven
- it is specialized or comparatively rare
- it contains many branches that would bloat the resident core
- it is operationally important but only occasionally needed

A subsystem may be:
- fully resident
- resident as a kernel plus detailed package
- package-only

RESIDENT ACCOUNTABILITY
- Do not let package discovery weaken the resident core.
- Before marking a subsystem package-only, verify that ordinary play remains runnable from core_rules.md plus parameter lookup.
- If package-only status would make ordinary play materially harder to run, mark resident_presence as "kernel" and ensure the descriptor says what kernel or lookup hook should be resident.
- If current_core_rules_md lacks that kernel or lookup boundary, still mark resident_presence as "kernel" and describe the missing resident expectation in "contains" / "source_cues" so downstream review can catch it.
- Package-only is appropriate for rare, specialized, long exception-rich, optional, or table-heavy material; it is not appropriate merely because the content is long or appears in a later chapter.

DISCOVERY OUTPUT MUST COVER FOUR THINGS
1. resident file registration
2. detailed rule package discovery
3. parameter family discovery
4. character sheet package discovery

PREFERRED DETAILED PACKAGE IDS
Use only these canonical detailed package ids:
- creation
- progression
- combat
- recovery
- exploration
- social
- abilities
- downtime_economy
- chase_vehicles
- hacking
- sanity
- mission

DETAILED PACKAGE DISCOVERY RULES
- Use the resident core as the baseline.
- Do not create a package merely because the rulebook has a chapter with that name.
- A package can exist even when its ordinary-play kernel is already resident.
- In such a case, mark resident_presence as "kernel".
- If a subsystem is already sufficiently covered in the resident core, omit it from detailed packages.
- Avoid overlap. Each detailed rule should have one best package home.
- If two registry items are inseparable in this book, merge into the better fit and explain why.
- Do not create free-form package ids.
- Prefer a small, high-value package set over package sprawl.

PARAMETER FAMILY DISCOVERY RULES
A family belongs in JSON only if most entries:
- repeat a stable structure
- are useful to query by name or id during play
- require exact values, tags, costs, thresholds, or restrictions
- or form lookup / roll / generation tables useful outside long prose explanation

Keep in markdown instead of JSON when content is:
- a small list of 10 items or fewer
- mostly descriptive or example-based
- too weakly structured
- tightly bound to a procedural flow
- only meaningful inside a rules explanation
- character-option material with no hard repeated fields

PREFERRED FAMILY IDS
Use these when they fit:
- spell
- power
- weapon
- armor
- item
- creature
- npc_template
- role
- feature
- condition
- disease
- poison
- vehicle
- program
- cyberware
- drug
- background
- occupation
- table_random
- table_price
- table_generation

If none fit cleanly, create a precise snake_case family_id.

CHARACTER SHEET PACKAGE DISCOVERY RULES
Decide whether this rulebook supports a separate character sheet package.
In almost all traditional TRPG rulebooks the answer will be yes.
The character sheet package consists of:
- character_sheet/character_sheet_template.json
- character_sheet/character_creation_guide.md

Mark present when the source provides enough information to derive:
- what a character must track
- how a character is created
- how key fields are calculated or updated

LINE HINTS REQUIREMENT (v6 extension)
For every discovered detailed_rule_package, parameter_family, and the character_sheet_package, emit a "line_hints" field:
- A list of [start_line, end_line] inclusive ranges pointing into the line-numbered source supplied below.
- Ranges should cover the primary location(s) where this subsystem / family / sheet is discussed.
- Keep ranges tight but complete; multiple short ranges are preferred over one huge span.
- If you cannot locate a range, emit an empty list []. Never invent line numbers.

ALIASES RULE
Keep alias coverage conservative and small.
Only include aliases that are clearly supported by the book or directly inferable from repeated official naming variation.

OUTPUT CONTRACT
Return only this file block. The JSON must be valid (no trailing commas, no comments):

<<<FILE:knowledge_manifest.json>>>
{
  "book_id": "{BOOK_ID}",
  "book_title": "{BOOK_TITLE}",
  "world_mode": "{WORLD_MODE}",
  "resident": {
    "core_file": "core_rules.md",
    "companion_file": "{COMPANION_FILE}"
  },
  "detailed_rule_packages": [
    {
      "package_id": "combat",
      "title": "",
      "resident_presence": "kernel",
      "detailed_package_needed": true,
      "summary": "",
      "load_when": [],
      "contains": [],
      "excludes": [],
      "native_labels": [],
      "source_cues": [],
      "line_hints": [[0, 0]],
      "file": "rule_packages/combat.md"
    }
  ],
  "parameter_families": [
    {
      "family_id": "weapon",
      "title": "",
      "summary": "",
      "entry_definition": "",
      "estimated_count": 0,
      "family_specific_fields": [],
      "native_labels": [],
      "source_cues": [],
      "line_hints": [[0, 0]],
      "file": "parameters/weapon.json"
    }
  ],
  "character_sheet_package": {
    "present": true,
    "summary": "",
    "template_file": "character_sheet/character_sheet_template.json",
    "guide_file": "character_sheet/character_creation_guide.md",
    "source_cues": [],
    "line_hints": [[0, 0]],
    "template_focus": [],
    "guide_focus": []
  },
  "aliases": [
    {
      "alias": "",
      "target_type": "resident_term",
      "target_id": ""
    }
  ]
}
<<<END_FILE>>>

QUALITY BAR
- The worst failure is pushing ordinary-play material out of the resident core.
- The second worst failure is creating too many detailed packages.
- The third worst failure is forcing weak JSON families or forgetting the character sheet package.
- The fourth worst failure is emitting invented or out-of-range line_hints.
"""


def discovery_user_prompt(
    *,
    book_id: str,
    book_title: str,
    world_mode: str,
    companion_file: str,
    output_language: str | None,
    current_core_rules_md: str,
    current_companion_md: str,
    book_markdown_lined: str,
    extra_hint: str | None = None,
) -> str:
    parts = [
        DISCOVERY_TASK,
        "",
        "INPUT METADATA",
        f"- BOOK_ID: {book_id}",
        f"- BOOK_TITLE: {book_title}",
        f"- WORLD_MODE: {world_mode}",
        f"- COMPANION_FILE: {companion_file}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        "",
        "CURRENT RESIDENT CORE",
        current_core_rules_md or "(not yet extracted — treat as empty)",
        "",
        "CURRENT COMPANION",
        current_companion_md or "(not yet extracted — treat as empty)",
    ]
    hint = (extra_hint or "").strip()
    if hint:
        parts += ["", "ADMIN EXTRA HINT", hint]
    parts += [
        "",
        "SOURCE (line-numbered — use the [Lnnnnn] prefixes to populate line_hints)",
        book_markdown_lined,
    ]
    return "\n".join(parts)
