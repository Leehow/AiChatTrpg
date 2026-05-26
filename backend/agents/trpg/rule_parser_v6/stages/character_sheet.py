"""Stage 6 — Character sheet package extraction.

Emits two artifacts from a single LLM call:
- character_sheet/character_sheet_template.json (strict JSON)
- character_sheet/character_creation_guide.md (markdown)

Retries once on JSON decode failure, since an invalid template
breaks downstream character creation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Sequence

from ..file_block_parser import find_block
from ..line_focus import build_narrow_excerpt
from ..llm_utils import (
    OnChunk,
    OnProgress,
    parse_strict_json,
    run_stage_llm,
    strict_json_retry_reminder,
)
from ..prompts import SHARED_SYSTEM, character_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "character_sheet"
TEMPLATE_FILE = "character_sheet/character_sheet_template.json"
GUIDE_FILE = "character_sheet/character_creation_guide.md"


def _summarize_template(tpl: Any) -> str:
    if not isinstance(tpl, dict):
        return "invalid"
    keys = [
        k for k in ("identity", "attributes", "skills", "equipment")
        if k in tpl
    ]
    return f"keys={len(tpl)} known_sections={keys}"


async def run_character_sheet_stage(
    *,
    book_id: str,
    book_title: str,
    output_language: Optional[str],
    character_descriptor: Dict[str, Any],
    current_core_rules_md: str,
    lined_view: str,
    raw_lines: Sequence[str],
    extra_hint: Optional[str],
    model: str,
    base_url: str,
    api_key: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> Dict[str, Any]:
    """Run Stage 6. Returns {"template_json", "template_content", "guide_content", ...}.

    Retries once if the template JSON fails to parse — re-renders the
    full two-file prompt with a strict-JSON reminder prepended.
    """
    line_hints = character_descriptor.get("line_hints") or []
    source_cues = character_descriptor.get("source_cues") or []
    excerpt, narrowed, stats = build_narrow_excerpt(
        lined_view=lined_view,
        raw_lines=raw_lines,
        line_hints=line_hints,
        source_cues=source_cues,
    )
    if on_progress:
        await on_progress(
            STAGE_NAME,
            f"Building character sheet package (narrowed={narrowed})",
        )

    user_message = character_user_prompt(
        book_id=book_id,
        book_title=book_title,
        output_language=output_language,
        character_descriptor=character_descriptor,
        current_core_rules_md=current_core_rules_md,
        source_excerpt=excerpt,
        excerpt_is_narrowed=narrowed,
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
        log_tag="V6-char",
    )

    template_text = find_block(blocks, TEMPLATE_FILE)
    guide_text = find_block(blocks, GUIDE_FILE)
    template_json: Optional[Dict[str, Any]] = None

    if template_text:
        try:
            template_json = parse_strict_json(template_text)
        except Exception as exc:
            logger.warning("[V6-char] template JSON parse failed: %s", exc)

    needs_retry = (template_json is None) or not (guide_text or "").strip()
    if needs_retry:
        retry_msg = (
            strict_json_retry_reminder()
            + "\n\nRe-emit BOTH file blocks (template + guide). "
            + "The template JSON MUST parse as strict JSON.\n\n"
            + user_message
        )
        if on_progress:
            await on_progress(
                STAGE_NAME,
                "Retrying character sheet with strict-JSON reminder...",
            )
        raw2, blocks2 = await run_stage_llm(
            stage=STAGE_NAME + ":retry",
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prefix=SHARED_SYSTEM,
            user_message=retry_msg,
            tracker=tracker,
            on_progress=on_progress,
            on_chunk=on_chunk,
            stream=stream,
            log_tag="V6-char-retry",
        )
        template_text2 = find_block(blocks2, TEMPLATE_FILE)
        guide_text2 = find_block(blocks2, GUIDE_FILE)
        if template_text2:
            template_json = parse_strict_json(template_text2)
            template_text = template_text2
        if guide_text2:
            guide_text = guide_text2
        raw = raw2

    if template_json is None:
        raise ValueError(
            "Stage 6 (character_sheet) template JSON invalid after retry",
        )
    if not (guide_text or "").strip():
        raise ValueError(
            "Stage 6 (character_sheet) missing character_creation_guide.md",
        )

    template_json.setdefault("book_id", book_id)
    template_json.setdefault("template_version", "1.0")
    template_content = json.dumps(template_json, ensure_ascii=False, indent=2)

    logger.info(
        "[V6-char] template=%s guide_chars=%d excerpt=%d",
        _summarize_template(template_json),
        len(guide_text or ""),
        stats.get("char_count", 0),
    )
    if on_progress:
        await on_progress(
            STAGE_NAME,
            f"Character sheet ready ({_summarize_template(template_json)})",
        )
    return {
        "template_json": template_json,
        "template_filename": TEMPLATE_FILE,
        "template_content": template_content,
        "guide_filename": GUIDE_FILE,
        "guide_content": guide_text,
        "excerpt_stats": stats,
        "raw": raw,
    }
