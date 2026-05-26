"""OpenAI-compatible client.

Used for: openai, deepseek, kimi, glm, doubao, qwen, grok.
All seven providers expose an OpenAI-spec /v1/chat/completions endpoint;
we vary only `base_url`, `api_key`, and `model`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .base import CachedPrompt, ChatMessage, StreamChunk

logger = logging.getLogger("chatrpg.llm.cache")


def _model_rejects_temperature(model: str) -> bool:
    """OpenAI reasoning models (gpt-5.x, o1, o3, codex) reject `temperature`."""
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4")) or "codex" in m


@dataclass
class OpenAICompatClient:
    provider: str
    model: str
    api_key: str
    base_url: str

    def __post_init__(self) -> None:
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        # GPT-5.x (and OpenAI o-series reasoning models) reject `temperature`.
        if not _model_rejects_temperature(self.model):
            kwargs["temperature"] = temperature
        if extra:
            kwargs.update(extra)

        stream = await self._client.chat.completions.create(**kwargs)
        try:
            async for event in stream:
                if not event.choices:
                    continue
                choice = event.choices[0]
                delta = ""
                if choice.delta and choice.delta.content:
                    delta = choice.delta.content
                yield StreamChunk(delta=delta, finish_reason=choice.finish_reason)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

    async def stream_chat_cached(
        self,
        prompt: CachedPrompt,
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Cache-friendly chat.completions layout.

        Layout (mirrors chatlab's DeepSeek strategy — works on any provider
        whose disk cache matches by token-0 prefix: DeepSeek, Qwen, Kimi,
        Doubao, etc.):

          system   = BP1                       byte-stable across turns
          user     = "[GM Context]\\n{BP2}"     stable when memory unchanged
          assistant= "Understood..."            anchor for the BP2 boundary
          ...history...                         grows monotonically
          user     = "[Per-turn Context]\\n{BP3}"
          assistant= "Understood."
          user     = real_user_message

        Putting BP3 in a tail user message keeps the BP1+BP2 prefix
        byte-stable when only BP3 changes, so the disk cache hits the
        biggest chunk of the request."""
        messages: list[dict[str, Any]] = []
        if prompt.stable_prefix:
            messages.append({"role": "system", "content": prompt.stable_prefix})
        if prompt.semi_stable_context:
            messages.append({
                "role": "user",
                "content": f"[GM Context]\n{prompt.semi_stable_context}",
            })
            messages.append({
                "role": "assistant",
                "content": "Understood. I have the context.",
            })
        for m in prompt.history:
            if m.role in ("user", "assistant") and m.content:
                messages.append({"role": m.role, "content": m.content})
        if prompt.variable_suffix:
            messages.append({
                "role": "user",
                "content": f"[Per-turn Context]\n{prompt.variable_suffix}",
            })
            messages.append({
                "role": "assistant",
                "content": "Understood.",
            })
        if prompt.user_message:
            messages.append({"role": "user", "content": prompt.user_message})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            # Required so cache_read counts arrive on the final chunk.
            "stream_options": {"include_usage": True},
        }
        if not _model_rejects_temperature(self.model):
            kwargs["temperature"] = temperature
        if extra:
            kwargs.update(extra)

        stream = await self._client.chat.completions.create(**kwargs)
        last_usage: Any = None
        try:
            async for event in stream:
                if event.usage is not None:
                    last_usage = event.usage
                if not event.choices:
                    continue
                choice = event.choices[0]
                delta = ""
                if choice.delta and choice.delta.content:
                    delta = choice.delta.content
                yield StreamChunk(delta=delta, finish_reason=choice.finish_reason)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass
        if last_usage is not None:
            details = getattr(last_usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            prompt = getattr(last_usage, "prompt_tokens", 0) or 0
            completion = getattr(last_usage, "completion_tokens", 0) or 0
            pct = (cached * 100 / prompt) if prompt else 0.0
            logger.info(
                "[CACHE %s/%s] prompt=%d cached=%d (%.0f%%) completion=%d",
                self.provider, self.model, prompt, cached, pct, completion,
            )
            yield StreamChunk(usage={
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": getattr(last_usage, "total_tokens", None),
                "prompt_tokens_details": {"cached_tokens": cached},
            })
