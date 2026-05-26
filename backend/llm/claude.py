"""Claude native streaming client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from .base import CachedPrompt, ChatMessage, StreamChunk

# Anthropic's `cache_control` ephemeral breakpoint with the 1-hour extended
# TTL: write costs 2x normal, read costs 0.1x. Break-even is two cache hits
# more than 5 minutes apart, which is the common case for TRPG turns where
# the player thinks for a while between sends.
_CACHE_CONTROL_1H = {"type": "ephemeral", "ttl": "1h"}
_CACHE_BETA_HEADER = (
    "prompt-caching-2024-07-31,extended-cache-ttl-2025-04-11"
)


@dataclass
class ClaudeClient:
    provider: str
    model: str
    api_key: str

    def __post_init__(self) -> None:
        self._client = AsyncAnthropic(api_key=self.api_key)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        system_text = "\n\n".join(m.content for m in messages if m.role == "system")
        chat_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": chat_msgs,
            "temperature": temperature,
            "max_tokens": 8192,  # Claude API requires this; not user-tunable.
        }
        if system_text:
            kwargs["system"] = system_text
        if extra:
            kwargs.update(extra)

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield StreamChunk(delta=text)

    async def stream_chat_cached(
        self,
        prompt: CachedPrompt,
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Multi-breakpoint prompt caching via `cache_control` blocks.

        Anthropic accepts up to 4 `cache_control` breakpoints per request.
        We use up to 3:
          1. system block 1 — `stable_prefix` (BP1, byte-stable)
          2. system block 2 — `semi_stable_context` (BP2, snapshot-stable)
          3. last history message — anchored history prefix
        BP3 (`variable_suffix`) is appended as a user message AFTER the
        breakpoint so it stays uncached. Each per-turn change only busts the
        prefix from BP3 forward."""
        system_blocks: list[dict[str, Any]] = []
        if prompt.stable_prefix:
            system_blocks.append({
                "type": "text",
                "text": prompt.stable_prefix,
                "cache_control": _CACHE_CONTROL_1H,
            })
        if prompt.semi_stable_context:
            system_blocks.append({
                "type": "text",
                "text": prompt.semi_stable_context,
                "cache_control": _CACHE_CONTROL_1H,
            })

        api_messages: list[dict[str, Any]] = []
        for m in prompt.history:
            if m.role in ("user", "assistant") and m.content:
                api_messages.append({"role": m.role, "content": m.content})

        # Anchor the last history message with the third breakpoint so the
        # whole history-up-to-N-1 prefix is also cached as turns accumulate.
        if api_messages:
            last = api_messages[-1]
            api_messages[-1] = {
                "role": last["role"],
                "content": [
                    {
                        "type": "text",
                        "text": last["content"],
                        "cache_control": _CACHE_CONTROL_1H,
                    }
                ],
            }

        # BP3 + real user message land AFTER the cached prefix. Wrapping BP3
        # in a fake "[GM Context]" turn keeps the actual user_message clean.
        if prompt.variable_suffix:
            api_messages.append({
                "role": "user",
                "content": f"[GM Context]\n{prompt.variable_suffix}",
            })
            api_messages.append({
                "role": "assistant",
                "content": "Understood. I have the context.",
            })
        if prompt.user_message:
            api_messages.append({"role": "user", "content": prompt.user_message})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": 8192,
            "extra_headers": {"anthropic-beta": _CACHE_BETA_HEADER},
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if extra:
            kwargs.update(extra)

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield StreamChunk(delta=text)
