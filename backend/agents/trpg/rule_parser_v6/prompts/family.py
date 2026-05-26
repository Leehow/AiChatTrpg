"""Prompt 5 — Parameter Family Extraction Prompt."""

from __future__ import annotations

import json
from typing import Any, Dict

from .system import output_language_clause


FAMILY_TASK = """Task: extract one parameter family as a queryable JSON file.

GOAL
Read the supplied source and the family descriptor, then produce:
1. parameters/{FAMILY_ID}.json

GENERAL RULES
- One object per canonical entry.
- Merge repeated mentions of the same entry across chapters, summaries, sidebars, and tables.
- Preserve exact numbers, costs, ranges, durations, requirements, action types, ratings, tags, restrictions, and explicit notes.
- Do not invent absent values.
- If a field exists in the schema but is absent for an entry, use null or [].
- Record aliases only when the book explicitly supports them.
- Keep summaries short and factual.
- If the family turns out to be too small, too unstable, or too process-dependent for JSON, return should_remain_markdown = true instead of forcing bad extraction.
- For catalog/table families, extract only source-backed entries. Do not turn each line into explanatory prose, do not repeat source text, and do not add narrative commentary.
- Keep each entry compact: one short summary, exact mechanical/table values in fields, and no long quotations.
- If the source is a large catalog that would require more than about 250 compact entries, return should_remain_markdown = true instead of producing an oversized or partial JSON.

LINE NUMBER RULE
If the source includes line numbers, treat them only as an internal focusing aid.
Do not emit line numbers, source spans, or reference blocks in the output.

COMMON OUTER SHELL
Every entry must contain:
- id
- name
- aliases
- family
- summary
- tags
- rule_context

ID RULE
Use stable serial ids in this format:
{BOOK_ID}.{FAMILY_ID}.001
{BOOK_ID}.{FAMILY_ID}.002
...

DEDUPE RULES
- Prefer the clearest full entry as canonical.
- Use repeated mentions only to fill missing fields or aliases.
- Do not keep near-duplicate entries.
- Be consistent about variants:
  - either separate them into separate entries
  - or keep one parent entry with a variants array
Choose one strategy for the whole family.

TABLE FAMILY RULES
For table_random:
- entries may be table rows rather than named objects
- include roll_notation where available
- include entries with roll_min, roll_max, result, notes, linked_refs

For table_price:
- include entries with item_name, price, currency, notes, linked_refs

For table_generation:
- include roll_notation where available
- include entries with roll_min, roll_max, result, downstream_effect, notes

PROCESS-DEPENDENT TABLE RULE
If the family only makes sense inside a long procedure and is not independently useful for lookup, do not force extraction. Return should_remain_markdown = true.

JSON VALIDITY
- Output must be strictly valid JSON. No comments. No trailing commas.
- All keys and string values must be double-quoted.
- Use null / [] / {} for missing fields; do not omit schema-declared fields.

OUTPUT CONTRACT
Return only this file block:

<<<FILE:parameters/{FAMILY_ID}.json>>>
{
  "book_id": "{BOOK_ID}",
  "family_id": "{FAMILY_ID}",
  "title": "",
  "should_remain_markdown": false,
  "schema_used": {
    "common_shell_fields": [
      "id",
      "name",
      "aliases",
      "family",
      "summary",
      "tags",
      "rule_context"
    ],
    "family_specific_fields": []
  },
  "entries": [
    {
      "id": "{BOOK_ID}.{FAMILY_ID}.001",
      "name": "",
      "aliases": [],
      "family": "{FAMILY_ID}",
      "summary": "",
      "tags": [],
      "rule_context": ""
    }
  ]
}
<<<END_FILE>>>

Stop immediately after the closing <<<END_FILE>>> marker. Do not repeat the file block and do not append explanations.

QUALITY BAR
- The worst failure is losing exact structured values.
- The second worst failure is duplicating the same entry.
- The third worst failure is inventing unsupported field values.
"""


def family_user_prompt(
    *,
    book_id: str,
    book_title: str,
    family_id: str,
    output_language: str | None,
    family_descriptor: Dict[str, Any],
    source_excerpt: str,
    excerpt_is_narrowed: bool,
    extra_hint: str | None = None,
) -> str:
    task = FAMILY_TASK.replace("{FAMILY_ID}", family_id).replace(
        "{BOOK_ID}", book_id,
    )
    descriptor_json = json.dumps(family_descriptor, ensure_ascii=False, indent=2)
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
        f"- FAMILY_ID: {family_id}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        "",
        "FAMILY DESCRIPTOR",
        descriptor_json,
    ]
    hint = (extra_hint or "").strip()
    if hint:
        parts += ["", "ADMIN EXTRA HINT", hint]
    parts += ["", source_label, source_excerpt]
    return "\n".join(parts)
