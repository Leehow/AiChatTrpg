from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class StreamChunk:
    delta: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class CachedPrompt:
    """Stability-graded prompt for cache-aware streaming.

    Each layer maps to a cache tier the provider treats independently:
      stable_prefix      — BP1: cached aggressively, byte-stable across turns.
      semi_stable_context — BP2: cached when memory snapshot didn't change.
      variable_suffix    — BP3: never cached, churns every turn.
    history + user_message follow the same shape they would in stream_chat."""

    stable_prefix: str = ""
    semi_stable_context: str = ""
    variable_suffix: str = ""
    history: list[ChatMessage] = field(default_factory=list)
    user_message: str = ""


class LLMClient(Protocol):
    provider: str
    model: str

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yield chunks of generated text. NEVER set max_tokens upstream."""
        ...

    async def stream_chat_cached(
        self,
        prompt: "CachedPrompt",
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream the LLM reply using provider-native prompt caching.

        Implementations route the layered prompt into the provider's cache
        machinery (Claude `cache_control` blocks, Gemini `systemInstruction`,
        OpenAI `instructions` / chat.completions message-pair layout). Default
        implementations may flatten back to `stream_chat` when caching is not
        supported."""
        ...
