"""Module-side NPC stat-block extraction.

When a module's appendix lists named NPCs / monsters / creatures with
mechanical numbers (HP, stats, skills), those numbers are authoritative —
the module designer wrote them deliberately. This step pulls each entry's
source text out of the markdown, asks an LLM to clean it into a
``params`` dict that mirrors the ruleset's character template, and stores
the result on ``parsed_module.semantic_structure["npc_cards"][]``.

Why LLM, not regex: appendix stat blocks are wildly inconsistent (free
prose mixed with bullet lists, varying labels per ruleset, occasional
table rows). Regex on raw markdown would only catch a fraction. The
character template gives the LLM a target shape so its output uses the
SAME parameter names the PC has — once a PC stat block is e.g.
``{STR: 60, CON: 60, ...}``, the NPC's params follow suit.

Ported from chatlab's ``agents/trpg/module_parser_cards.py`` and adapted
to chatrpg's ``module_semantic`` pipeline conventions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.module_semantic_llm import call_json


logger = logging.getLogger("chatrpg.module_npc_cards")


_CARD_TYPES = {"npc", "monster", "creature", "character"}
_CONTEXT_LINES = 200
_MAX_CONTEXT_CHARS = 8000


_CARD_SYSTEM_PROMPT = """You normalize one TRPG module appendix entry into a structured character card.

You will receive:
- The entity's index entry (name, type, brief, stats_summary)
- A slice of the source markdown (~200 lines around the entry)
- The ruleset's character sheet template — the AUTHORITATIVE shape for parameter names

Your job: output a JSON card with mechanical params that match the ruleset template's parameter names.

## Output JSON shape (no markdown fences)
{
  "name": "<full display name>",
  "type": "npc" | "monster" | "creature",
  "brief": "<one-line role summary>",
  "description": "<2-3 sentence physical + personality description if present>",
  "appearance": "<short physical description, may be empty>",
  "personality": "<traits, mannerisms, may be empty>",
  "motivation": "<what drives them in this module, may be empty>",
  "dialogue_style": "<speech tone / accent / quirks, may be empty>",
  "abilities": ["<distinctive ability 1>", "..."],
  "params": {"<param_name>": <number or short string>, ...},
  "params_context": "<one-line justification, e.g. 'directly from appendix stat block' or 'inferred from prose: weak civilian'>",

  "relationship_to_pc": "preexisting_relationship" | "plot_informed" | "stranger",
  "interest_score": <int 0-10>,
  "interest_drive_kind": "neutral" | "social" | "affinity" | "professional" | "relationship" | "goal_driven" | "mixed",
  "interest_reason": "<one line: why this drive exists>",
  "emotional_state": "<2-6 words: their default disposition>",
  "secret_agenda": "<GM-only hidden goal, may be empty>",
  "interaction_goals": ["<concrete thing they want from PC if/when met>", "..."]
}

## Rules for psychology fields
- Module appendix NPCs almost always default to `relationship_to_pc: "stranger"`
  unless the source text says they are hunting, briefed about, or
  pre-acquainted with the PC.
- `interest_score` rubric (use the lowest band that fits):
  0 avoids · 1-2 passive · 3-4 mild contextual · 5-6 actively engages
  · 7-8 strongly wants something specific · 9-10 obsessive/mission-critical.
- `interest_drive_kind` should reflect WHY they care: `goal_driven` for
  hunters/investigators, `professional` for guards/officers/doctors,
  `relationship` for relatives/old friends, `social`/`affinity` for chatty
  bond-seekers, `neutral` for passing strangers.

## Rules for `params`
- Use the SAME parameter names the ruleset character template uses (snake_case English keys).
- COPY values verbatim when the source text states them outright.
- If the source has prose ("a tough farmer in his fifties") but no numbers,
  INFER reasonable values that match the ruleset's value range. Note this
  in `params_context` as "inferred".
- Include ONLY numerical / mechanical fields (core attributes, HP, MP, key
  skills, damage modifiers, build, dodge, armor). Skip narrative fields.
- 1-2 role-specific numeric traits are fine if the source describes a
  unique ability with a number.
- Empty `params` is acceptable when the source has no mechanics at all
  (use `params_context: "no mechanical data in source"`).

## Rules for narrative fields
- Match the source language (Chinese source → Chinese output for narrative
  fields; param names stay snake_case English).
- Don't invent secrets or facts not in the text. Empty string is fine.
- For monsters/creatures, focus `abilities` on combat / horror traits.

Output the JSON object ONLY, no preamble, no fences."""


_USER_TEMPLATE = """## Index entry
Name: {name}
Type: {type}
Brief: {brief}
Stats summary (raw): {stats_summary}

## Ruleset character template (parameter shape)
{template}

## Source markdown slice (around line L{line})
{source_text}"""


async def extract_module_npc_cards(
    db: AsyncSession,
    *,
    markdown: str,
    appendix_entries: list[dict[str, Any]],
    character_template: str,
) -> list[dict[str, Any]]:
    """LLM-clean the eligible appendix entries into structured NPC cards.

    Returns a list of card dicts. Failures per-entry are logged and
    skipped — one bad LLM response should not lose the whole batch.
    """
    eligible = [
        entry for entry in (appendix_entries or [])
        if isinstance(entry, dict) and _is_eligible(entry)
    ]
    if not eligible or not markdown:
        return []

    template_text = (character_template or "").strip()
    if len(template_text) > 4000:
        # The template is reference material, not the meat of the prompt.
        # Leave room for the source slice.
        template_text = template_text[:4000] + "\n…(template truncated)"
    elif not template_text:
        template_text = "(no character template available — use ruleset-conventional names)"

    lines = markdown.splitlines()
    cards: list[dict[str, Any]] = []
    for entry in eligible:
        card = await _extract_one(db, lines, entry, template_text)
        if card:
            cards.append(card)
    return cards


def _is_eligible(entry: dict[str, Any]) -> bool:
    typ = str(entry.get("type") or "").strip().lower()
    if typ in _CARD_TYPES:
        return True
    # Some module indexers don't always tag the type cleanly. Fall back on
    # the brief / name when "stats_summary" looks mechanical, since a
    # statless entity wouldn't help us anyway.
    stats_summary = str(entry.get("stats_summary") or "").strip()
    if not stats_summary:
        return False
    return bool(_NUMERIC_HINT_RE.search(stats_summary))


_NUMERIC_HINT_RE = re.compile(
    r"\d+\s*[/]\s*\d+|\bHP\b|\bSAN\b|\bSTR\b|\bDEX\b|\bCON\b|\bD\d+\b|\b\d+%\b",
    re.I,
)


async def _extract_one(
    db: AsyncSession,
    lines: list[str],
    entry: dict[str, Any],
    template_text: str,
) -> dict[str, Any] | None:
    name = str(entry.get("name") or "").strip()
    if not name:
        return None

    line_no = _safe_int(entry.get("line"))
    source_text = _slice_around_line(lines, line_no)
    if not source_text:
        # Fall back to the entry's own brief / stats_summary so the LLM at
        # least sees what the indexer captured.
        source_text = (
            f"{entry.get('brief', '')}\n{entry.get('stats_summary', '')}"
        ).strip()
        if not source_text:
            return None

    user_message = _USER_TEMPLATE.format(
        name=name,
        type=str(entry.get("type") or "npc"),
        brief=str(entry.get("brief") or "(none)"),
        stats_summary=str(entry.get("stats_summary") or "(none)"),
        template=template_text,
        line=line_no or "?",
        source_text=source_text[:_MAX_CONTEXT_CHARS],
    )

    try:
        card = await call_json(db, _CARD_SYSTEM_PROMPT, user_message)
    except Exception:
        logger.warning(
            "[chatrpg.module_npc_cards] LLM call failed for entry %s",
            name, exc_info=True,
        )
        return None
    if not isinstance(card, dict):
        return None

    card = _normalise_card(card, entry, name)
    return card


def _slice_around_line(lines: list[str], line_no: int) -> str:
    if not line_no or line_no < 1 or line_no > len(lines):
        return ""
    start = max(0, line_no - 1)
    end = min(len(lines), line_no + _CONTEXT_LINES)
    return "\n".join(lines[start:end])


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalise_card(
    card: dict[str, Any],
    entry: dict[str, Any],
    fallback_name: str,
) -> dict[str, Any]:
    """Clean up keys / types so downstream code can rely on them."""
    out: dict[str, Any] = {}
    out["name"] = str(card.get("name") or fallback_name).strip() or fallback_name
    out["type"] = str(card.get("type") or entry.get("type") or "npc").strip().lower() or "npc"
    out["brief"] = str(card.get("brief") or entry.get("brief") or "").strip()
    for field in ("description", "appearance", "personality", "motivation", "dialogue_style"):
        value = card.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()

    abilities = card.get("abilities")
    if isinstance(abilities, list):
        out["abilities"] = [
            str(item).strip() for item in abilities if str(item).strip()
        ]

    # Psychology hints — pass through what the LLM emitted so
    # ``_npc_payload`` can seed inner_state / player_knowledge from the
    # module author's classification instead of falling back to the
    # keyword regex when the NPC enters a session.
    psych_relationship = str(card.get("relationship_to_pc") or "").strip().lower()
    if psych_relationship in {"preexisting_relationship", "plot_informed", "stranger"}:
        out["llm_relationship_hint"] = psych_relationship
    psych_interest = card.get("interest_score")
    if isinstance(psych_interest, (int, float)):
        out["player_interest"] = max(0, min(10, int(psych_interest)))
    psych_drive = str(card.get("interest_drive_kind") or "").strip().lower()
    psych_reason = str(card.get("interest_reason") or "").strip()
    if psych_drive in {"neutral", "social", "affinity", "professional", "relationship", "goal_driven", "mixed"} or psych_reason:
        drive: dict[str, Any] = {}
        if psych_drive:
            drive["kind"] = psych_drive
        if psych_reason:
            drive["reason"] = psych_reason
        if psych_drive in {"goal_driven", "mixed"}:
            drive["decays_on_goal_satisfied"] = True
        out["interest_drive"] = drive
    psych_emotion = str(card.get("emotional_state") or "").strip()
    if psych_emotion:
        out["emotional_state"] = psych_emotion
    psych_secret = str(card.get("secret_agenda") or "").strip()
    if psych_secret:
        out["secret_agenda"] = psych_secret
    psych_goals = card.get("interaction_goals")
    if isinstance(psych_goals, list) and psych_goals:
        out["interaction_goals"] = [str(g).strip() for g in psych_goals if str(g).strip()]

    params = card.get("params") or {}
    if isinstance(params, dict):
        cleaned: dict[str, Any] = {}
        for key, value in params.items():
            key_norm = str(key or "").strip()
            if not key_norm:
                continue
            cleaned[key_norm] = value
        if cleaned:
            out["params"] = cleaned
            ctx = str(card.get("params_context") or "").strip()
            out["params_context"] = ctx or "from module appendix"

    out["source"] = str(entry.get("source") or "")
    out["source_range"] = str(entry.get("source_range") or "")
    if entry.get("line"):
        out["source_line"] = _safe_int(entry.get("line"))

    return out


def safe_dump(card: dict[str, Any]) -> str:
    """JSON-dump a card for log lines / debug. Bounded length."""
    try:
        return json.dumps(card, ensure_ascii=False)[:300]
    except Exception:
        return str(card)[:300]
