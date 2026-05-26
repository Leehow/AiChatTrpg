"""ChatLab-compatible module parser adapter for AiChatTrpg."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.module_semantic_llm import call_json, call_text
from services.module_semantic_shared import ensure_shared_parser_path

ensure_shared_parser_path()

import trpg_module_parser_core as parser_core  # noqa: E402

MAX_TOKENS = parser_core.MAX_TOKENS
SPLIT_THRESHOLD = parser_core.SPLIT_THRESHOLD
SPLIT_TARGET = parser_core.SPLIT_TARGET
MERGE_THRESHOLD = parser_core.MERGE_THRESHOLD
MERGE_CAP = parser_core.MERGE_CAP
VALID_TYPES = parser_core.VALID_TYPES
ANCHOR_TO_MODULE = parser_core.ANCHOR_TO_MODULE
PLAYABLE_TYPES = parser_core.PLAYABLE_TYPES
APPENDIX_TYPES = parser_core.APPENDIX_TYPES
OTHER_TYPES = parser_core.OTHER_TYPES

clean_sections = parser_core.clean_sections
merge_small_sections = parser_core.merge_small_sections
split_structure_packs = parser_core.split_structure_packs
section_texts = parser_core.section_texts
numbered_section_text = parser_core.numbered_section_text
line_span = parser_core.line_span
pack_step_summary = parser_core.pack_step_summary
estimate_mixed_tokens = parser_core.estimate_mixed_tokens


async def parse_structure_llm(
    db: AsyncSession,
    markdown: str,
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    async def adapter(system_prompt: str, user_content: str) -> dict[str, Any] | None:
        return await call_json(db, system_prompt, user_content)

    return await parser_core.parse_structure(markdown, profile, adapter)


async def rebalance_playable_llm(
    db: AsyncSession,
    markdown: str,
    playable: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    async def adapter(system_prompt: str, user_content: str) -> dict[str, Any] | None:
        return await call_json(db, system_prompt, user_content)

    return await parser_core.rebalance_playable(markdown, playable, adapter)


async def distill_briefing(
    db: AsyncSession,
    markdown: str,
    sections: list[dict[str, Any]],
) -> str:
    async def adapter(system_prompt: str, user_content: str) -> str:
        return await call_text(db, system_prompt, user_content)

    return await parser_core.distill_briefing(markdown, sections, adapter)


async def index_appendix_lists(
    db: AsyncSession,
    markdown: str,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    async def adapter(system_prompt: str, user_content: str) -> dict[str, Any] | None:
        return await call_json(db, system_prompt, user_content)

    return await parser_core.index_appendix_lists(markdown, sections, adapter)
