"""Gemini native streaming client."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from google import genai
from google.genai import types as genai_types

from .base import CachedPrompt, ChatMessage, StreamChunk

logger = logging.getLogger("chatrpg.llm.cache")


@dataclass
class GeminiClient:
    provider: str
    model: str
    api_key: str

    def __post_init__(self) -> None:
        self._client = genai.Client(api_key=self.api_key)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        system_text = "\n\n".join(m.content for m in messages if m.role == "system")
        contents: list[genai_types.Content] = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role == "user" else "model"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part(text=m.content)])
            )

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_text or None,
        )

        stream = self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        )
        if isawaitable(stream):
            stream = await stream
        async for chunk in stream:
            text = getattr(chunk, "text", "") or ""
            if text:
                yield StreamChunk(delta=text)

    async def stream_chat_cached(
        self,
        prompt: CachedPrompt,
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Implicit caching via `system_instruction`.

        Gemini's implicit cache hits when `system_instruction` bytes match
        the previous request. We park BP1 there. BP2 + BP3 ride along as
        `[GM Context]` user-prefix turns inside `contents` (uncached but
        accepted as part of the regular turn flow). Wrapping BP3 in its own
        turn keeps the real user_message clean for the model."""
        contents: list[genai_types.Content] = []
        if prompt.semi_stable_context:
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"[GM Context]\n{prompt.semi_stable_context}")],
            ))
            contents.append(genai_types.Content(
                role="model",
                parts=[genai_types.Part(text="Understood. I have the context.")],
            ))
        for m in prompt.history:
            if m.role not in ("user", "assistant") or not m.content:
                continue
            role = "user" if m.role == "user" else "model"
            contents.append(genai_types.Content(
                role=role, parts=[genai_types.Part(text=m.content)],
            ))
        if prompt.variable_suffix:
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"[Per-turn Context]\n{prompt.variable_suffix}")],
            ))
            contents.append(genai_types.Content(
                role="model",
                parts=[genai_types.Part(text="Understood.")],
            ))
        if prompt.user_message:
            contents.append(genai_types.Content(
                role="user", parts=[genai_types.Part(text=prompt.user_message)],
            ))

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=prompt.stable_prefix or None,
        )

        stream = self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        )
        if isawaitable(stream):
            stream = await stream
        last_usage: Any = None
        async for chunk in stream:
            text = getattr(chunk, "text", "") or ""
            if text:
                yield StreamChunk(delta=text)
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                last_usage = usage
        if last_usage is not None:
            cached = (
                getattr(last_usage, "cached_content_token_count", 0)
                or 0
            )
            prompt_tokens = getattr(last_usage, "prompt_token_count", 0) or 0
            completion = getattr(last_usage, "candidates_token_count", 0) or 0
            pct = (cached * 100 / prompt_tokens) if prompt_tokens else 0.0
            logger.info(
                "[CACHE %s/%s] prompt=%d cached=%d (%.0f%%) completion=%d",
                self.provider, self.model, prompt_tokens, cached, pct, completion,
            )
            yield StreamChunk(usage={
                "usage_metadata": {
                    "prompt_token_count": prompt_tokens,
                    "cached_content_token_count": cached,
                    "candidates_token_count": completion,
                }
            })
