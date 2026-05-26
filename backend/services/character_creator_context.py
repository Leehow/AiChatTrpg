"""Context-packet construction and debug thinking events for character creation.

Builds the structured rulebook + module + character-sheet context that the
prompts wrap, plus the BP1/BP2/BP3 thinking lines surfaced via the debug
panel.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, ParsedModule, Ruleset

from services.character_creator_state import CharacterContext


def _ruleset_template_json(ruleset: Ruleset) -> dict[str, Any] | None:
    """Pull `template_json` out of a ruleset's parsed_v6, if present.

    The strict-template filter and the schema-hint generator both want
    the structured template (not the flat `template_content` markdown).
    Returns None when the ruleset has no JSON template, which disables
    the strict filter for legacy file-based templates.
    """
    raw = ruleset.parsed_v6 if isinstance(ruleset.parsed_v6, dict) else {}
    sheet = raw.get("character_sheet")
    if not isinstance(sheet, dict):
        return None
    tj = sheet.get("template_json")
    if isinstance(tj, dict) and tj:
        return tj
    return None


async def _build_context(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
) -> str:
    return (await _build_context_packet(db, session, ruleset)).context


async def _build_context_packet(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
) -> CharacterContext:
    raw = ruleset.parsed_v6 if isinstance(ruleset.parsed_v6, dict) else {}
    sheet = raw.get("character_sheet") if isinstance(raw.get("character_sheet"), dict) else {}
    template = (
        sheet.get("template_content")
        or _json_dumps(sheet.get("template_json"))
        or ""
    )
    guide = str(sheet.get("guide_content") or "")
    core = str(raw.get("core_rules") or "")
    companion = raw.get("companion") if isinstance(raw.get("companion"), dict) else {}
    scene_guide = str(companion.get("content") or "")

    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    module_text = ""
    module_title = ""
    module_id = str(setup.get("module_id") or "")
    if module_id and module_id != "__freeform__":
        row = await db.get(ParsedModule, module_id)
        if row and (row.owner_id == session.user_id or row.is_shared):
            module_title = str(row.extracted_title or setup.get("module_title") or row.filename)
            # Chargen ships the KP briefing only — full module markdown
            # would spoil plot for the player before play begins.
            briefing = str(row.briefing_md or "")
            module_text = f"Title: {module_title}\n{briefing}" if briefing else ""
    elif setup.get("module_title"):
        module_title = str(setup.get("module_title") or "")
        module_text = f"Title: {module_title}"

    parts = [
        f"## Ruleset\nTitle: {ruleset.book_title}\nWorld mode: {ruleset.world_mode}",
        f"## Core Rules\n{core or '(none)'}",
        f"## Scene Guide\n{scene_guide or '(none)'}",
        f"## Character Sheet Template\n{template or '(none)'}",
        f"## Character Creation Guide\n{guide or '(none)'}",
        f"## Module Context\n{module_text or '(freeform / no module selected)'}",
    ]
    context = "\n\n".join(parts)
    return CharacterContext(
        context=context,
        ruleset_title=ruleset.book_title,
        core_chars=len(core),
        scene_chars=len(module_text),
        creation_chars=len(template) + len(guide),
        scene_guide_chars=len(scene_guide),
        module_count=1 if module_text else 0,
        module_title=module_title,
        module_text=module_text,
        scene_guide=scene_guide,
    )


def _thinking_events(
    packet: CharacterContext,
    session: GameSession,
    *,
    stage: str,
    chat_msgs: int,
    model: str,
    provider: str,
    temperature: float,
    prompt_system_chars: int,
    prompt_user_chars: int,
) -> list[str]:
    """Build debug thinking lines from real state. Every value comes from the
    live packet / session / prompt — no fixed templates."""
    lines: list[str] = [f"[stage] {stage}"]

    # BP1 — stable context loaded from the ruleset
    bp1 = [f"ruleset={packet.ruleset_title or '?'}"]
    bp1.append(f"core_rules={packet.core_chars}")
    bp1.append(f"scene_guide={packet.scene_guide_chars}")
    bp1.append(f"sheet+guide={packet.creation_chars}")
    if packet.scene_chars:
        bp1.append(f"module={packet.module_title or '?'}({packet.scene_chars})")
    else:
        bp1.append("module=none")
    lines.append("[BP1 stable] " + " | ".join(bp1))

    # BP2 — memory snapshot (read live; setup phase is normally empty)
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    bp2 = [
        f"scenes={len(mem.get('scenes') or [])}",
        f"npcs={len(mem.get('npcs') or [])}",
        f"plots={len(mem.get('plot_threads') or [])}",
        f"facts={len(mem.get('world_facts') or [])}",
    ]
    narr = (session.narrative_summary or "").strip()
    if narr:
        bp2.append(f"summary={len(narr)}")
    lines.append("[BP2 memory] " + " | ".join(bp2))

    # BP3 — per-turn live state
    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    bp3 = [
        f"chat_msgs={chat_msgs}",
        f"pc={'present' if session.character else 'none'}",
        f"draft_card={'present' if setup.get('character_card') else 'none'}",
        f"ready={'true' if setup.get('character_ready') else 'false'}",
    ]
    lines.append("[BP3 turn] " + " | ".join(bp3))

    lines.append(f"[llm] provider={provider} model={model} temperature={temperature}")
    total = prompt_system_chars + prompt_user_chars
    lines.append(
        f"[prompt] system={prompt_system_chars} user={prompt_user_chars} total={total}"
    )
    return lines


def _json_dumps(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)
