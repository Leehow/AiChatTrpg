"""Provider-specific prompt compiler.

Keep provider-specific cache knobs here, not in the memory service.
"""

from __future__ import annotations

from typing import Any

from .models import CompiledContext, Provider, ProviderPrompt


class PromptCompiler:
    def compile(self, *, provider: Provider, model: str, context: CompiledContext) -> ProviderPrompt:
        if provider == Provider.OPENAI:
            return self._openai(model, context)
        if provider == Provider.ANTHROPIC:
            return self._anthropic(model, context)
        if provider == Provider.GEMINI:
            return self._gemini(model, context)
        return self._local(model, context)

    def _openai(self, model: str, context: CompiledContext) -> ProviderPrompt:
        # Responses API / Chat Completions adapters can map this payload into
        # their exact request shape. The key is that prefix_text is the first
        # unchanged message and dynamic_text is appended after it.
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": context.prefix_text},
                {"role": "user", "content": context.dynamic_text},
            ],
            "prompt_cache_key": context.cache_key,
            "metadata": {
                "prefix_hash": context.prefix_hash,
                "visibility_signature": context.visibility_signature,
            },
        }
        return ProviderPrompt(
            provider=Provider.OPENAI,
            model=model,
            payload=payload,
            cache_key=context.cache_key,
            prefix_hash=context.prefix_hash,
            block_version_ids=tuple(b.versioned_id for b in [*context.prefix_blocks, *context.pinned_blocks, *context.dynamic_blocks]),
        )

    def _anthropic(self, model: str, context: CompiledContext) -> ProviderPrompt:
        # Anthropic supports cache_control on content blocks. Keep the stable
        # prefix in a cacheable system block and leave the turn tail uncached.
        payload: dict[str, Any] = {
            "model": model,
            "system": [
                {
                    "type": "text",
                    "text": context.prefix_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": context.dynamic_text}],
                }
            ],
            "metadata": {
                "cache_key": context.cache_key,
                "prefix_hash": context.prefix_hash,
                "visibility_signature": context.visibility_signature,
            },
        }
        return ProviderPrompt(
            provider=Provider.ANTHROPIC,
            model=model,
            payload=payload,
            cache_key=context.cache_key,
            prefix_hash=context.prefix_hash,
            block_version_ids=tuple(b.versioned_id for b in [*context.prefix_blocks, *context.pinned_blocks, *context.dynamic_blocks]),
        )

    def _gemini(self, model: str, context: CompiledContext) -> ProviderPrompt:
        # For implicit caching, send prefix first. For explicit caching, create
        # a CachedContent from context.prefix_text elsewhere and pass its name
        # here as cached_content_ref.
        payload: dict[str, Any] = {
            "model": model,
            "contents": [
                {"role": "user", "parts": [{"text": context.prefix_text}]},
                {"role": "user", "parts": [{"text": context.dynamic_text}]},
            ],
            "metadata": {
                "cache_key": context.cache_key,
                "prefix_hash": context.prefix_hash,
                "visibility_signature": context.visibility_signature,
            },
        }
        return ProviderPrompt(
            provider=Provider.GEMINI,
            model=model,
            payload=payload,
            cache_key=context.cache_key,
            prefix_hash=context.prefix_hash,
            block_version_ids=tuple(b.versioned_id for b in [*context.prefix_blocks, *context.pinned_blocks, *context.dynamic_blocks]),
        )

    def _local(self, model: str, context: CompiledContext) -> ProviderPrompt:
        payload = {
            "model": model,
            "prompt": f"{context.prefix_text}\n\n{context.dynamic_text}",
            "prefix_hash": context.prefix_hash,
        }
        return ProviderPrompt(
            provider=Provider.LOCAL,
            model=model,
            payload=payload,
            cache_key=context.cache_key,
            prefix_hash=context.prefix_hash,
            block_version_ids=tuple(b.versioned_id for b in [*context.prefix_blocks, *context.pinned_blocks, *context.dynamic_blocks]),
        )
