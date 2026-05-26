"""Stage 1 — Thick Resident Core extraction.

Consumes the plain whole-book view. Emits core_rules.md as a single
markdown string. The pipeline caches this string in the v6 artifact
blob and passes it to later stages that need "current resident core"
context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..file_block_parser import find_block
from ..llm_utils import OnChunk, OnProgress, run_stage_llm
from ..prompts import SHARED_SYSTEM, core_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "core"
EXPECTED_FILE = "core_rules.md"


async def run_core_stage(
    *,
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
    """Run Stage 1 and return the resident core markdown.

    Returns {"content": "<markdown>", "raw": "<full llm response>"}.
    Raises ValueError when the LLM returns no usable block.
    """
    if on_progress:
        await on_progress(STAGE_NAME, "Compiling thick resident core...")

    user_message = core_user_prompt(
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
        log_tag="V6-core",
    )
    content = find_block(blocks, EXPECTED_FILE)
    if not content or not content.strip():
        raise ValueError(
            f"Stage 1 (core) produced no <<<FILE:{EXPECTED_FILE}>>> block",
        )
    logger.info("[V6-core] core_rules.md chars=%d", len(content))
    if on_progress:
        await on_progress(
            STAGE_NAME,
            f"Resident core ready ({len(content):,} chars)",
        )
    return {"content": content, "raw": raw}
