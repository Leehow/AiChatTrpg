"""LlmAdapter implementation + provider-usage normalization for IC turns.

Extracted from `services.trpg_ic_runner` to keep the orchestrator near the
project's 400-line soft target. Behavior, signatures, and the framework
contract are unchanged — `ChatrpgLlmAdapter` still satisfies the framework's
`LlmAdapter` Protocol via duck typing and `_llm_cache_metrics_from_usage`
still produces the same trace-safe metrics dict the runner records.
"""

from __future__ import annotations

from typing import Any

from agents.trpg.framework.adapters.protocols import LlmDelta
from agents.trpg.framework.models import LayeredPrompt
from llm import ChatMessage as LlmChatMessage
from llm import build_client
from llm.base import CachedPrompt


class ChatrpgLlmAdapter:
    """Wraps chatrpg's `build_client` into the framework's `LlmAdapter`.

    Translates `PromptMessage` ↔ `ChatMessage` and adapts the chunk shape so
    the framework only ever sees `LlmDelta`. Provider routing, prompt cache,
    and any future provider-specific knobs stay inside `build_client`."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self.last_usage: dict[str, Any] | None = None

    async def stream_chat(  # noqa: ARG002 — model carried in init
        self,
        messages,
        *,
        model,
        layered_prompt: LayeredPrompt | None = None,
    ):
        client = build_client(
            self._provider, self._model, self._api_key, self._base_url,
        )
        # Cache-aware path: when the IC builder hands us a layered prompt and
        # the client implements `stream_chat_cached`, route through provider-
        # native caching (Claude cache_control, Gemini systemInstruction,
        # OpenAI/DeepSeek system+user-pair layout). Falls back to the legacy
        # single-system message shape for clients without cache support
        # (mock + any future client that doesn't override).
        cached_fn = getattr(client, "stream_chat_cached", None)
        if layered_prompt is not None and callable(cached_fn):
            cached = CachedPrompt(
                stable_prefix=layered_prompt.stable_prefix,
                semi_stable_context=layered_prompt.semi_stable_context,
                variable_suffix=layered_prompt.variable_suffix,
                history=[
                    LlmChatMessage(role=m.role, content=m.content)
                    for m in layered_prompt.history
                ],
                user_message=layered_prompt.user_message,
            )
            async for chunk in cached_fn(cached, temperature=self._temperature):
                if chunk.usage:
                    self.last_usage = dict(chunk.usage)
                if chunk.delta:
                    yield LlmDelta(delta=chunk.delta)
            yield LlmDelta(delta="", is_final=True, raw={"usage": self.last_usage} if self.last_usage else None)
            return
        llm_messages = [
            LlmChatMessage(role=m.role, content=m.content) for m in messages
        ]
        async for chunk in client.stream_chat(
            llm_messages, temperature=self._temperature,
        ):
            if chunk.usage:
                self.last_usage = dict(chunk.usage)
            if chunk.delta:
                yield LlmDelta(delta=chunk.delta)
        yield LlmDelta(delta="", is_final=True, raw={"usage": self.last_usage} if self.last_usage else None)


def _llm_cache_metrics_from_usage(
    *,
    provider: str,
    model: str,
    usage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize provider usage into trace-safe cache metrics."""

    if not isinstance(usage, dict) or not usage:
        return {"prompt_provider": provider, "prompt_model": model, "usage_available": False}

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None

    if "usage_metadata" in usage or "usageMetadata" in usage:
        meta = usage.get("usage_metadata") or usage.get("usageMetadata") or {}
        if isinstance(meta, dict):
            input_tokens = _int_or_none(meta.get("prompt_token_count") or meta.get("promptTokenCount"))
            output_tokens = _int_or_none(meta.get("candidates_token_count") or meta.get("candidatesTokenCount"))
            cached_tokens = _int_or_none(meta.get("cached_content_token_count") or meta.get("cachedContentTokenCount"))
    else:
        input_tokens = _int_or_none(usage.get("prompt_tokens") or usage.get("input_tokens"))
        output_tokens = _int_or_none(usage.get("completion_tokens") or usage.get("output_tokens"))
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        if isinstance(details, dict):
            cached_tokens = _int_or_none(details.get("cached_tokens"))
        cached_tokens = cached_tokens if cached_tokens is not None else _int_or_none(usage.get("cache_read_input_tokens"))

    hit_ratio = None
    if input_tokens and cached_tokens is not None:
        hit_ratio = cached_tokens / max(input_tokens, 1)

    return {
        "prompt_provider": provider,
        "prompt_model": model,
        "usage_available": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_ratio": hit_ratio,
    }


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ChatrpgLlmAdapter",
    "_llm_cache_metrics_from_usage",
    "_int_or_none",
]
