"""Cache telemetry extraction.

Adapters should call CacheMetrics.record_after_call() with the raw provider
response. This keeps metrics normalized across OpenAI, Anthropic, Gemini, and
local inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import ProviderPrompt


@dataclass(frozen=True)
class CacheMetric:
    provider: str
    model: str
    cache_key: str
    prefix_hash: str
    input_tokens: int | None
    cached_tokens: int | None
    cache_hit_ratio: float | None
    block_version_ids: tuple[str, ...]


class CacheMetrics:
    def from_provider_response(self, prompt: ProviderPrompt, raw_response: Mapping[str, Any]) -> CacheMetric:
        if prompt.provider.value == "openai":
            input_tokens, cached_tokens = self._openai_usage(raw_response)
        elif prompt.provider.value == "anthropic":
            input_tokens, cached_tokens = self._anthropic_usage(raw_response)
        elif prompt.provider.value == "gemini":
            input_tokens, cached_tokens = self._gemini_usage(raw_response)
        else:
            input_tokens, cached_tokens = None, None

        hit_ratio = None
        if input_tokens and cached_tokens is not None:
            hit_ratio = cached_tokens / max(input_tokens, 1)

        return CacheMetric(
            provider=prompt.provider.value,
            model=prompt.model,
            cache_key=prompt.cache_key,
            prefix_hash=prompt.prefix_hash,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            cache_hit_ratio=hit_ratio,
            block_version_ids=prompt.block_version_ids,
        )

    def _openai_usage(self, response: Mapping[str, Any]) -> tuple[int | None, int | None]:
        usage = response.get("usage") or {}
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        cached_tokens = details.get("cached_tokens")
        return input_tokens, cached_tokens

    def _anthropic_usage(self, response: Mapping[str, Any]) -> tuple[int | None, int | None]:
        usage = response.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        # Anthropic may expose cache_read/cache_creation counts separately.
        cached_tokens = usage.get("cache_read_input_tokens")
        return input_tokens, cached_tokens

    def _gemini_usage(self, response: Mapping[str, Any]) -> tuple[int | None, int | None]:
        usage = response.get("usage_metadata") or response.get("usageMetadata") or {}
        input_tokens = usage.get("prompt_token_count") or usage.get("promptTokenCount")
        cached_tokens = usage.get("cached_content_token_count") or usage.get("cachedContentTokenCount")
        return input_tokens, cached_tokens
