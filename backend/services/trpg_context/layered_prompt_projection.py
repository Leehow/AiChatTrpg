"""Map framework LayeredPrompt objects into ContextBuilder blocks.

This is the P4 bridge between the existing BP1/BP2/BP3 prompt builder and the
new context/cache model. The live LLM prompt still uses the framework's
LayeredPrompt directly; this module produces an observability projection for
TurnTrace/debug and for later prompt-compiler rollout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.trpg.framework.models import LayeredPrompt, PromptMessage

from .block_store import InMemoryBlockStore
from .canonical import estimate_tokens, normalize_content, sha256_text
from .context_builder import ContextBuilder
from .models import (
    ActorScope,
    BlockKind,
    CacheZone,
    CompiledContext,
    ContextBlock,
    ContextProfile,
    ContextRequest,
    DynamicContext,
    Provider,
    Stability,
    Visibility,
)
from .prompt_compiler import PromptCompiler


@dataclass(frozen=True)
class LayeredPromptProjection:
    """Compiled context plus compact metadata safe to store on TurnTrace."""

    compiled_context: CompiledContext
    metadata: dict[str, Any]


def compile_layered_prompt_context(
    *,
    layered_prompt: LayeredPrompt,
    provider: str,
    model: str,
    ruleset_id: str,
    campaign_id: str,
    session_id: str,
    scene_id: str | None,
    turn_id: str,
    chapter_id: str | None = None,
    location_id: str | None = None,
    npc_ids_in_scene: tuple[str, ...] = (),
) -> LayeredPromptProjection:
    """Project an existing BP layered prompt into ContextBuilder metadata.

    BP1 (`stable_prefix`) becomes a prefix block. BP2
    (`semi_stable_context`) becomes a pinned-middle session block. BP3
    (`variable_suffix`) plus recent history/current input become turn-dynamic
    blocks. This intentionally does not replace the runtime prompt yet.
    """

    normalized_provider = _normalize_provider(provider)
    store = InMemoryBlockStore(
        _static_blocks_from_layered_prompt(
            layered_prompt=layered_prompt,
            ruleset_id=ruleset_id,
            session_id=session_id,
        )
    )
    builder = ContextBuilder(store)
    request = ContextRequest(
        actor=ActorScope(
            profile=ContextProfile.GM,
            campaign_id=campaign_id,
            session_id=session_id,
            scene_id=scene_id or None,
        ),
        provider=normalized_provider,
        model=model,
        ruleset_id=ruleset_id,
        campaign_id=campaign_id,
        chapter_id=chapter_id,
        location_id=location_id,
        npc_ids_in_scene=npc_ids_in_scene,
        dynamic=DynamicContext(
            turn_id=turn_id,
            world_state=_bp3_world_state(layered_prompt.variable_suffix),
            recent_transcript=_history_payload(layered_prompt.history),
            current_input=layered_prompt.user_message,
        ),
    )
    compiled = builder.build(request)
    provider_prompt = PromptCompiler().compile(
        provider=normalized_provider,
        model=model,
        context=compiled,
    )

    prefix_ids = tuple(block.versioned_id for block in compiled.prefix_blocks)
    pinned_ids = tuple(block.versioned_id for block in compiled.pinned_blocks)
    dynamic_ids = tuple(block.versioned_id for block in compiled.dynamic_blocks)
    metadata = {
        "provider": normalized_provider.value,
        "raw_provider": str(provider or ""),
        "model": model,
        "cache_key": provider_prompt.cache_key,
        "prefix_hash": provider_prompt.prefix_hash,
        "visibility_signature": compiled.visibility_signature,
        "block_version_ids": list(provider_prompt.block_version_ids),
        "prefix_block_ids": list(prefix_ids),
        "pinned_block_ids": list(pinned_ids),
        "dynamic_block_ids": list(dynamic_ids),
        "block_count": len(provider_prompt.block_version_ids),
        "prefix_block_count": len(prefix_ids),
        "pinned_block_count": len(pinned_ids),
        "dynamic_block_count": len(dynamic_ids),
        "token_estimate": compiled.token_estimate,
        "prefix_chars": len(compiled.prefix_text),
        "dynamic_chars": len(compiled.dynamic_text),
        "stable_prefix_hash": sha256_text(layered_prompt.stable_prefix or ""),
        "semi_stable_hash": sha256_text(layered_prompt.semi_stable_context or ""),
        "variable_suffix_hash": sha256_text(layered_prompt.variable_suffix or ""),
        "history_hash": sha256_text(_history_render(layered_prompt.history)),
        "user_message_hash": sha256_text(layered_prompt.user_message or ""),
        "history_count": len(layered_prompt.history),
        "layer_chars": {
            "stable_prefix": len(layered_prompt.stable_prefix or ""),
            "semi_stable_context": len(layered_prompt.semi_stable_context or ""),
            "variable_suffix": len(layered_prompt.variable_suffix or ""),
            "history": sum(len(message.content or "") for message in layered_prompt.history),
            "user_message": len(layered_prompt.user_message or ""),
        },
        "blocks": [_block_metadata(block) for block in [
            *compiled.prefix_blocks,
            *compiled.pinned_blocks,
            *compiled.dynamic_blocks,
        ]],
        "projection": "layered_prompt_v1",
    }
    return LayeredPromptProjection(compiled_context=compiled, metadata=metadata)


def _static_blocks_from_layered_prompt(
    *,
    layered_prompt: LayeredPrompt,
    ruleset_id: str,
    session_id: str,
) -> list[ContextBlock]:
    blocks: list[ContextBlock] = []
    if (layered_prompt.stable_prefix or "").strip():
        content = layered_prompt.stable_prefix
        blocks.append(
            ContextBlock(
                block_id=f"session.{session_id}.bp1.stable_prefix",
                kind=BlockKind.CAMPAIGN_STATIC,
                title="BP1 stable prefix",
                content=content,
                visibility=Visibility.GM_ONLY,
                stability=Stability.IMMUTABLE,
                cache_zone=CacheZone.PREFIX,
                version=_version_for_text(content),
                scope_type="session",
                scope_id=session_id,
                content_hash=sha256_text(content),
                token_estimate=estimate_tokens(content),
                priority=100,
                tags=("bp1", "layered_prompt"),
            )
        )
    if (layered_prompt.semi_stable_context or "").strip():
        content = layered_prompt.semi_stable_context
        blocks.append(
            ContextBlock(
                block_id=f"session.{session_id}.bp2.memory_context",
                kind=BlockKind.SESSION_SUMMARY,
                title="BP2 memory and session context",
                content=content,
                visibility=Visibility.GM_ONLY,
                stability=Stability.SESSION_PINNED,
                cache_zone=CacheZone.PINNED_MIDDLE,
                version=_version_for_text(content),
                scope_type="session",
                scope_id=session_id,
                content_hash=sha256_text(content),
                token_estimate=estimate_tokens(content),
                priority=95,
                tags=("bp2", "layered_prompt"),
            )
        )
    if not blocks:
        content = {"ruleset_id": ruleset_id, "note": "empty layered prompt"}
        text = normalize_content(content)
        blocks.append(
            ContextBlock(
                block_id=f"session.{session_id}.bp.empty",
                kind=BlockKind.ENGINE_PROTOCOL,
                title="Empty BP projection placeholder",
                content=content,
                visibility=Visibility.SYSTEM_INTERNAL,
                stability=Stability.IMMUTABLE,
                cache_zone=CacheZone.PREFIX,
                version=_version_for_text(text),
                scope_type="session",
                scope_id=session_id,
                content_hash=sha256_text(text),
                priority=1,
                tags=("bp", "empty"),
            )
        )
    return blocks


def _bp3_world_state(variable_suffix: str) -> dict[str, Any]:
    if not (variable_suffix or "").strip():
        return {}
    return {
        "bp3_variable_suffix": variable_suffix,
    }


def _history_payload(messages: list[PromptMessage]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for message in messages:
        payload.append({
            "role": str(message.role),
            "content": str(message.content or ""),
        })
    return payload


def _history_render(messages: list[PromptMessage]) -> str:
    return "\n\n".join(
        f"{message.role}: {message.content or ''}"
        for message in messages
    )


def _normalize_provider(provider: str) -> Provider:
    value = (provider or "").strip().lower()
    if value in {Provider.OPENAI.value, "openrouter", "deepseek", "qwen", "siliconflow"}:
        return Provider.OPENAI
    if value in {Provider.ANTHROPIC.value, "claude"}:
        return Provider.ANTHROPIC
    if value in {Provider.GEMINI.value, "google"}:
        return Provider.GEMINI
    if value in {Provider.LOCAL.value, "ollama", "lmstudio"}:
        return Provider.LOCAL
    return Provider.OPENAI


def _version_for_text(text: str) -> int:
    digest = sha256_text(text or "")
    # Keep versions deterministic while avoiding zero, which reads poorly in
    # debug output and some storage backends treat as "unset".
    return max(1, int(digest[:8], 16))


def _block_metadata(block: ContextBlock) -> dict[str, Any]:
    content_hash = block.content_hash
    if not content_hash:
        content_hash = sha256_text(normalize_content(block.content or ""))
    return {
        "block_id": block.block_id,
        "versioned_id": block.versioned_id,
        "kind": block.kind.value,
        "cache_zone": block.cache_zone.value,
        "visibility": block.visibility.value,
        "stability": block.stability.value,
        "scope_type": block.scope_type,
        "scope_id": block.scope_id,
        "content_hash": content_hash,
        "token_estimate": block.token_estimate,
        "priority": block.priority,
        "tags": list(block.tags),
    }
