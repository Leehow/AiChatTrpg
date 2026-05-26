"""Prompt 6 — Character Sheet Package Extraction Prompt."""

from __future__ import annotations

import json
from typing import Any, Dict

from .system import output_language_clause


CHARACTER_TASK = """Task: extract the character sheet package for the rulebook.

GOAL
Read the supplied source, the resident core, and the descriptor, then produce:
1. character_sheet/character_sheet_template.json
2. character_sheet/character_creation_guide.md

PURPOSE OF THE PACKAGE
This package is meant to support both:
- character creation
- ongoing runtime tracking of character state

It is not just a visual mockup of a sheet.
It must be usable as structured game state.

LINE NUMBER RULE
If the source includes line numbers, treat them only as an internal focusing aid.
Do not emit line numbers, source spans, or reference blocks in the output.

TEMPLATE REQUIREMENTS
The template must be complete enough to support the system actually described by the book.
Include the fields a player or LLM GM would need to track in play.

Unless the source strongly requires a better arrangement, structure the template around these sections:
- identity
- origin
- attributes
- modifiers
- derived_values
- resources
- classes_roles
- skills
- feats_features
- abilities_spells
- languages
- equipment
- currency_and_progression
- statuses
- notes

RULES FOR THE TEMPLATE
- If the book contains an explicit sheet or a detailed sheet explanation, adapt that structure closely.
- If not, derive a practical runtime template from creation, progression, combat, equipment, and ability rules.
- Do not invent values the source does not support.
- Use null, [], or {} for empty defaults.
- Keep field naming consistent and machine-usable.
- Prefer sectioned structure over a huge flat object.
- Include system-specific fields when they are important.

TEMPLATE JSON VALIDITY
- The template MUST be strictly valid JSON. No comments. No trailing commas.
- All keys and string values must be double-quoted.
- If you are unsure about a field type, prefer null over omitting the field.
- The template JSON block will be parsed programmatically — invalid JSON fails the whole stage.

GUIDE REQUIREMENTS
character_creation_guide.md must explain:
- the order of creation
- mandatory choices
- optional choices
- how to determine starting values
- how to calculate derived values
- how to assign skills, classes, feats, abilities, gear, money, languages, and similar fields
- what changes during play
- what is typically updated after a mission/session

The guide should be procedural, not essay-like.

SUGGESTED GUIDE STRUCTURE
# Character Creation Guide
## 1. What the Character Sheet Tracks
## 2. Character Creation Order
## 3. Mandatory Choices
## 4. Attribute and Modifier Calculation
## 5. Derived Values and Resources
## 6. Classes, Roles, Skills, and Features
## 7. Equipment, Currency, and Loadout
## 8. Languages, Notes, and Special Fields
## 9. What Changes During Play
## 10. What to Update After a Session

OUTPUT CONTRACT
Return only these file blocks:

<<<FILE:character_sheet/character_sheet_template.json>>>
{
  "book_id": "{BOOK_ID}",
  "template_version": "1.0",
  "identity": {},
  "origin": {},
  "attributes": {},
  "modifiers": {},
  "derived_values": {},
  "resources": {},
  "classes_roles": [],
  "skills": [],
  "feats_features": [],
  "abilities_spells": [],
  "languages": [],
  "equipment": {
    "weapons": [],
    "armor": [],
    "accessories": [],
    "items": []
  },
  "currency_and_progression": {},
  "statuses": [],
  "notes": {}
}
<<<END_FILE>>>

<<<FILE:character_sheet/character_creation_guide.md>>>
...markdown...
<<<END_FILE>>>

QUALITY BAR
- The worst failure is producing a sheet that cannot support actual play.
- The second worst failure is omitting derived values or update rules.
- The third worst failure is creating a visually plausible but operationally weak template.
- The fourth worst failure is emitting invalid JSON in the template.
"""


def character_user_prompt(
    *,
    book_id: str,
    book_title: str,
    output_language: str | None,
    character_descriptor: Dict[str, Any],
    current_core_rules_md: str,
    source_excerpt: str,
    excerpt_is_narrowed: bool,
    extra_hint: str | None = None,
) -> str:
    task = CHARACTER_TASK.replace("{BOOK_ID}", book_id)
    descriptor_json = json.dumps(character_descriptor, ensure_ascii=False, indent=2)
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
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        "",
        "CHARACTER SHEET DESCRIPTOR",
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
