"""Stage 5 — Per-family parameter extraction (strict JSON).

Called once per entry in manifest.parameter_families. Uses
line_focus.build_narrow_excerpt() to narrow the source before
prompting and enforces one-retry-on-JSON-failure via
run_strict_json_stage().
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from ..line_focus import build_narrow_excerpt
from ..llm_utils import (
    OnChunk,
    OnProgress,
    run_strict_json_stage,
    strict_json_retry_reminder,
)
from ..prompts import SHARED_SYSTEM, family_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "family"
_EMPTY_LINED_ROW_RE = re.compile(r"^\[L\d+\]\s*$")


def _family_file(family_id: str) -> str:
    return f"parameters/{family_id}.json"


async def run_family_stage(
    *,
    book_id: str,
    book_title: str,
    output_language: Optional[str],
    family_descriptor: Dict[str, Any],
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
    """Run Stage 5 for one family. Returns {"family_id", "filename", "json", ...}."""
    family_id = str(family_descriptor.get("family_id") or "").strip()
    if not family_id:
        raise ValueError("family_descriptor missing family_id")
    filename = _family_file(family_id)

    line_hints = family_descriptor.get("line_hints") or []
    source_cues = family_descriptor.get("source_cues") or []
    excerpt, narrowed, stats = build_narrow_excerpt(
        lined_view=lined_view,
        raw_lines=raw_lines,
        line_hints=line_hints,
        source_cues=source_cues,
    )
    excerpt = _drop_empty_lined_rows(excerpt)
    stats["char_count"] = len(excerpt)
    stage_tag = f"{STAGE_NAME}:{family_id}"
    if on_progress:
        await on_progress(
            stage_tag,
            f"Extracting family '{family_id}' (narrowed={narrowed})",
        )

    user_message = family_user_prompt(
        book_id=book_id,
        book_title=book_title,
        family_id=family_id,
        output_language=output_language,
        family_descriptor=family_descriptor,
        source_excerpt=excerpt,
        excerpt_is_narrowed=narrowed,
        extra_hint=extra_hint,
    )
    retry_msg = strict_json_retry_reminder() + "\n\n" + user_message

    parsed, raw, _blocks = await run_strict_json_stage(
        stage=stage_tag,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=SHARED_SYSTEM,
        user_message=user_message,
        expected_filename=filename,
        retry_user_message=retry_msg,
        tracker=tracker,
        on_progress=on_progress,
        on_chunk=on_chunk,
        stream=stream,
        log_tag=f"V6-fam-{family_id}",
    )
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Family '{family_id}' JSON root must be an object, got {type(parsed).__name__}",
        )
    parsed.setdefault("book_id", book_id)
    parsed.setdefault("family_id", family_id)
    entries = parsed.get("entries") or []
    should_md = bool(parsed.get("should_remain_markdown"))
    logger.info(
        "[V6-fam-%s] entries=%d should_remain_markdown=%s excerpt=%d",
        family_id, len(entries), should_md, stats.get("char_count", 0),
    )
    if on_progress:
        await on_progress(
            stage_tag,
            (f"Family '{family_id}' kept in markdown (descriptor rejected JSON fit)"
             if should_md else
             f"Family '{family_id}' ready ({len(entries)} entries)"),
        )
    content = json.dumps(parsed, ensure_ascii=False, indent=2)
    return {
        "family_id": family_id,
        "filename": filename,
        "json": parsed,
        "content": content,
        "excerpt_stats": stats,
        "should_remain_markdown": should_md,
        "raw": raw,
    }


async def run_families(
    *,
    families: List[Dict[str, Any]],
    book_id: str,
    book_title: str,
    output_language: Optional[str],
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
) -> List[Dict[str, Any]]:
    """Sequential family extraction — same rationale as run_packages."""
    out: List[Dict[str, Any]] = []
    for descriptor in families:
        descriptor_copy = dict(descriptor)
        try:
            result = await run_family_stage(
                book_id=book_id,
                book_title=book_title,
                output_language=output_language,
                family_descriptor=descriptor_copy,
                lined_view=lined_view,
                raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model,
                base_url=base_url,
                api_key=api_key,
                tracker=tracker,
                on_progress=on_progress,
                on_chunk=on_chunk,
                stream=stream,
            )
            out.append(result)
        except Exception as exc:
            fam_id = descriptor_copy.get("family_id", "?")
            logger.error("[V6-fam] %s failed: %s", fam_id, exc)
            if on_progress:
                await on_progress(
                    f"{STAGE_NAME}:{fam_id}",
                    f"Family '{fam_id}' failed: {exc}",
                )
            out.append({
                "family_id": fam_id,
                "filename": _family_file(str(fam_id)),
                "json": None,
                "content": "",
                "error": str(exc),
            })
    return out


def _drop_empty_lined_rows(excerpt: str) -> str:
    """Remove blank numbered rows from sparse parameter-source excerpts."""
    if not excerpt:
        return excerpt
    lines = [
        line
        for line in excerpt.splitlines()
        if not _EMPTY_LINED_ROW_RE.match(line.strip())
    ]
    return "\n".join(lines)
