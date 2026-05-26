"""Shared LLM call helpers for v6 stages.

Thin layer over `rule_parser_v4.llm_call.call_llm` that:
- wraps stage-specific progress callbacks
- parses `<<<FILE:...>>>` blocks
- tolerates one JSON-validation retry where callers need strict JSON
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agents.trpg.rule_parser_v4.llm_call import TokenTracker, call_llm

from .file_block_parser import FileBlockParseError, parse_file_blocks

logger = logging.getLogger("chatlab.trpg")

OnProgress = Optional[Callable[[str, str], Awaitable[None]]]
OnChunk = Optional[Callable[[str, str], Awaitable[None]]]


async def run_stage_llm(
    *,
    stage: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prefix: str,
    user_message: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
    log_tag: str = "V6",
) -> Tuple[str, List[Dict[str, str]]]:
    """Run one LLM call and parse its FILE blocks.

    Returns (raw_text, file_blocks). Callers decide whether empty
    blocks are a hard failure.
    """
    async def _chunk(text: str):
        if on_chunk:
            await on_chunk(stage, text)

    raw = await call_llm(
        model, base_url, api_key,
        system_prefix=system_prefix,
        user_message=user_message,
        stage=stage,
        tracker=tracker,
        log_tag=log_tag,
        on_chunk=_chunk,
        stream=stream,
    )
    if not raw:
        if on_progress:
            await on_progress(stage, "LLM returned empty response")
        return "", []
    try:
        blocks = parse_file_blocks(raw)
    except FileBlockParseError as exc:
        logger.warning("[%s] block parse failed: %s", log_tag, exc)
        if on_progress:
            await on_progress(stage, f"block parse failed: {exc}")
        return raw, []
    return raw, blocks


def parse_strict_json(text: str) -> Any:
    """Parse JSON with one lenient pass that strips leading/trailing fences."""
    body = (text or "").strip()
    if not body:
        raise ValueError("empty JSON")
    if body.startswith("```"):
        # Strip a fenced code block if the model wrapped it.
        first_nl = body.find("\n")
        if first_nl > 0:
            body = body[first_nl + 1:]
        if body.endswith("```"):
            body = body[:-3]
        body = body.strip()
    return json.loads(body)


async def run_strict_json_stage(
    *,
    stage: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prefix: str,
    user_message: str,
    expected_filename: str,
    retry_user_message: Optional[str] = None,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
    log_tag: str = "V6",
) -> Tuple[Any, str, List[Dict[str, str]]]:
    """Run an LLM call where one FILE block must be strict JSON.

    On first JSON decode failure, retries once with an optional
    retry user message (caller can supply a tightened version, e.g.
    quoting the failed block). Returns (parsed_obj, raw, blocks).
    Raises ValueError on a second failure.
    """
    raw, blocks = await run_stage_llm(
        stage=stage, model=model, base_url=base_url, api_key=api_key,
        system_prefix=system_prefix, user_message=user_message,
        tracker=tracker, on_progress=on_progress, on_chunk=on_chunk,
        stream=stream, log_tag=log_tag,
    )
    block_text = _find_block_text(blocks, expected_filename)
    if block_text is not None:
        try:
            return parse_strict_json(block_text), raw, blocks
        except Exception as exc:
            logger.warning("[%s] first JSON parse failed: %s", log_tag, exc)

    retry_msg = retry_user_message or user_message
    if on_progress:
        await on_progress(stage, "Retrying with strict-JSON reminder...")
    raw2, blocks2 = await run_stage_llm(
        stage=stage + ":retry", model=model, base_url=base_url, api_key=api_key,
        system_prefix=system_prefix, user_message=retry_msg,
        tracker=tracker, on_progress=on_progress, on_chunk=on_chunk,
        stream=stream, log_tag=log_tag + "-retry",
    )
    block_text2 = _find_block_text(blocks2, expected_filename)
    if block_text2 is None:
        raise ValueError(
            f"Missing <<<FILE:{expected_filename}>>> block after retry",
        )
    return parse_strict_json(block_text2), raw2, blocks2


def _find_block_text(
    blocks: List[Dict[str, str]],
    filename: str,
) -> Optional[str]:
    for block in blocks:
        if block.get("filename") == filename:
            return block.get("content") or ""
    return None


def strict_json_retry_reminder() -> str:
    return (
        "REMINDER: The previous response could not be parsed as JSON.\n"
        "Return only the requested <<<FILE:...>>> block.\n"
        "The block body MUST be strictly valid JSON:\n"
        "- no comments\n- no trailing commas\n- double-quoted keys and strings\n"
        "- no ellipses or placeholder text\n"
        "Re-emit the same artifact, correctly formatted this time."
    )
