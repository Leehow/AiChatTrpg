"""Compatibility shim for ChatLab rule_parser_v6 stages.

ChatLab v6 imports ``TokenTracker`` and ``call_llm`` from its v4 parser.
AiChatTrpg does not carry that whole parser, so this small adapter routes calls
through AiChatTrpg's OpenAI-compatible compiler client.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from agents.trpg.llm_json import call_llm_json_task

OnChunk = Optional[Callable[[str], Awaitable[None]]]
logger = logging.getLogger("chatrpg.rule_parser_v4.llm_call")


@dataclass
class TokenTracker:
    calls: int = 0
    input: int = 0
    output: int = 0
    cached: int = 0
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_estimate(self, stage: str, user_message: str, output_text: str) -> None:
        in_tokens = max(1, len(user_message) // 4)
        out_tokens = max(1, len(output_text) // 4)
        self.calls += 1
        self.input += in_tokens
        self.output += out_tokens
        self.stages[stage] = {
            "calls": self.stages.get(stage, {}).get("calls", 0) + 1,
            "input": self.stages.get(stage, {}).get("input", 0) + in_tokens,
            "output": self.stages.get(stage, {}).get("output", 0) + out_tokens,
            "cached": self.stages.get(stage, {}).get("cached", 0),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": {
                "calls": self.calls,
                "input": self.input,
                "output": self.output,
                "cached": self.cached,
                "cache_hit_rate": 0.0,
            },
            "stages": self.stages,
        }


async def call_llm(
    model: str,
    base_url: str,
    api_key: str,
    *,
    system_prefix: str,
    user_message: str,
    stage: str,
    tracker: TokenTracker | None = None,
    log_tag: str = "V6",
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> str:
    output_limit = _stage_output_limit(stage)

    async def _chunk(_stage: str, text: str) -> None:
        nonlocal output_seen
        output_seen += len(text or "")
        if output_limit and output_seen > output_limit:
            raise RuntimeError(
                f"{stage} stream output exceeded {output_limit} characters",
            )
        if on_chunk:
            await on_chunk(text)

    last_exc: Exception | None = None
    for attempt in range(2):
        output_seen = 0
        actual_stage = stage if attempt == 0 else f"{stage}:transport_retry"
        try:
            text = await call_llm_json_task(
                stage=actual_stage,
                model=model,
                base_url=base_url,
                api_key=api_key,
                system_prefix=system_prefix,
                user_message=user_message,
                stream=stream,
                on_chunk=_chunk,
            )
            break
        except Exception as exc:  # noqa: BLE001 - normalize relay flakes
            last_exc = exc
            if attempt == 0 and _should_retry_llm_error(exc):
                logger.warning(
                    "[%s] %s stream failed once, retrying: %s",
                    log_tag,
                    stage,
                    exc,
                )
                await asyncio.sleep(1.0)
                continue
            raise
    else:
        if last_exc is not None:
            raise last_exc
        text = ""
    if tracker:
        tracker.add_estimate(stage, user_message, text)
    return text


def _should_retry_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "context_length_exceeded" in message:
        return False
    if "stream output exceeded" in message:
        return False
    retry_terms = (
        "incomplete chunked read",
        "peer closed connection",
        "remoteprotocolerror",
        "connection reset",
        "timed out",
        "timeout",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
    )
    return any(term in message for term in retry_terms)


def _stage_output_limit(stage: str) -> int | None:
    """Catch pathological streams without constraining normal long stages."""
    if stage.startswith("family:"):
        return 260_000
    if stage.startswith("character_sheet"):
        return 220_000
    return None
