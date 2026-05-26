"""SceneBeatPlan rendering helpers that avoid duplicate prompt injection."""

from __future__ import annotations

import json
from typing import Any

from .common import get_value, set_value, to_plain_data


DEFAULT_SECTION_KEY = "npc_beat_plan"


def render_npc_beat_plan_section(beat_plan: Any, *, max_chars: int = 4000) -> str:
    """Render a compact NPC Beat Plan section for ``build_ic_context``."""

    plain = to_plain_data(beat_plan) or {}
    if not plain:
        return ""
    text = json.dumps(plain, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[: max_chars - 80] + "\n... <NPC Beat Plan truncated>"
    return (
        "## NPC Beat Plan\n"
        "This is the adjudicated NPC intent/reaction plan for this turn. "
        "Use must_include_beats when they fit the player's action. "
        "Do not reveal forbidden_fact_ids or blocked actions as facts.\n"
        "```json\n"
        f"{text}\n"
        "```"
    )


def install_extras_section(ctx: Any, key: str, text: str) -> Any:
    """Install one named extras section without appending duplicates.

    If your context object only has ``extras_text``, this function still works by
    maintaining an internal ``extras_sections`` dict when possible.  Prefer using
    sections and rendering them once at the end of context construction.
    """

    if not text:
        return ctx
    sections = get_value(ctx, "extras_sections")
    if sections is None:
        sections = {}
        set_value(ctx, "extras_sections", sections)
    if not isinstance(sections, dict):
        sections = {}
        set_value(ctx, "extras_sections", sections)
    sections[key] = text
    set_value(ctx, "extras_text", render_extras_sections(sections))
    return ctx


def render_extras_sections(sections: dict[str, str]) -> str:
    ordered_keys = [DEFAULT_SECTION_KEY] + sorted(k for k in sections if k != DEFAULT_SECTION_KEY)
    chunks = [sections[k].strip() for k in ordered_keys if sections.get(k)]
    return "\n\n".join(chunks).strip()
