"""Generate phase — runs the LLM on the prompt produced by preprocess and
streams the reply.

The framework owns only the streaming loop + ready-marker detection. Anything
project-specific (provider routing, GPT Responses tool retrieval, prompt
caching keepalive, native Gemini / Claude clients, etc.) lives behind the
LlmAdapter implementation."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Union

from ..models import TrpgServices, TurnInputs
from .preprocess import PreprocessOutput


@dataclass
class FinalReply:
    text: str
    ready: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ContentChunk:
    delta: str
    type: Literal["content"] = "content"


@dataclass
class _Final:
    reply: FinalReply
    type: Literal["final"] = "final"


GenerateEvent = Union[_ContentChunk, _Final]


@dataclass
class GenerateOutput:
    reply: FinalReply


# Hidden ready-marker the LLM can emit at the end of a setup turn to signal
# "the character draft is good enough to write a card from". chatrpg's
# character creator uses both this and `[CREATE_CHARACTER]` as triggers.
_READY_MARKER = re.compile(
    r"\s*<CHATRPG_READY>\s*(true|false)\s*</CHATRPG_READY>\s*",
    re.IGNORECASE,
)
_CREATE_CHAR_TRIGGER = "[CREATE_CHARACTER]"


async def generate(
    inputs: TurnInputs,
    prep: PreprocessOutput,
    services: TrpgServices,
) -> AsyncIterator[GenerateEvent]:
    """Stream the LLM reply, yield each delta, and emit a single _Final at
    the end with `text` cleaned of internal markers and `ready` decided."""
    raw_parts: list[str] = []
    ready = False
    async for delta in services.llm.stream_chat(
        prep.prompt_messages,
        model=inputs.model,
        layered_prompt=prep.layered_prompt,
    ):
        if delta.delta:
            raw_parts.append(delta.delta)
            yield _ContentChunk(delta=delta.delta)
        if delta.is_final:
            break
    raw = "".join(raw_parts)
    cleaned, ready = _strip_ready_signals(raw)
    yield _Final(reply=FinalReply(
        text=cleaned.strip(),
        ready=ready,
        metadata={"raw_chars": len(raw), "cleaned_chars": len(cleaned.strip())},
    ))


def _strip_ready_signals(text: str) -> tuple[str, bool]:
    """Pull out hidden ready signals and return (cleaned_text, ready)."""
    ready = False
    if _CREATE_CHAR_TRIGGER in text:
        ready = True
    m = _READY_MARKER.search(text)
    if m is not None:
        ready = ready or (m.group(1).lower() == "true")
        text = _READY_MARKER.sub("", text)
    return text, ready
