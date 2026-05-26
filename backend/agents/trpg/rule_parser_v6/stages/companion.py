"""Stage 2 — Companion file extraction (world_guide OR style_guide).

The human operator chooses world_mode per book:
- "worldview"  → produce world_guide.md
- "style_only" → produce style_guide.md

Only one companion file is produced per book.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..file_block_parser import find_block
from ..llm_utils import OnChunk, OnProgress, run_stage_llm
from ..prompts import SHARED_SYSTEM, companion_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "companion"


def companion_filename_for_mode(world_mode: str) -> str:
    mode = (world_mode or "worldview").strip().lower()
    return "style_guide.md" if mode == "style_only" else "world_guide.md"


async def run_companion_stage(
    *,
    world_mode: str,
    book_id: str,
    book_title: str,
    output_language: Optional[str],
    book_markdown_plain: str,
    extra_hint: Optional[str],
    model: str,
    base_url: str,
    api_key: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> Dict[str, Any]:
    """Run Stage 2. Returns {"filename", "content", "world_mode", "raw"}."""
    filename = companion_filename_for_mode(world_mode)
    mode_label = "style_only" if filename == "style_guide.md" else "worldview"
    if on_progress:
        await on_progress(
            STAGE_NAME, f"Compiling companion ({mode_label})...",
        )

    user_message = companion_user_prompt(
        world_mode=mode_label,
        book_id=book_id,
        book_title=book_title,
        output_language=output_language,
        book_markdown_plain=book_markdown_plain,
        extra_hint=extra_hint,
    )
    raw, blocks = await run_stage_llm(
        stage=STAGE_NAME,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=SHARED_SYSTEM,
        user_message=user_message,
        tracker=tracker,
        on_progress=on_progress,
        on_chunk=on_chunk,
        stream=stream,
        log_tag="V6-companion",
    )
    content = find_block(blocks, filename)
    if not content or not content.strip():
        raise ValueError(
            f"Stage 2 (companion) produced no <<<FILE:{filename}>>> block",
        )
    logger.info(
        "[V6-companion] %s chars=%d mode=%s",
        filename, len(content), mode_label,
    )
    if on_progress:
        await on_progress(
            STAGE_NAME,
            f"Companion ready ({filename}, {len(content):,} chars)",
        )
    return {
        "filename": filename,
        "content": content,
        "world_mode": mode_label,
        "raw": raw,
    }
