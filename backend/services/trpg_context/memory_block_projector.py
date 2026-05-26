"""Project committed MemoryItem objects into cache-aware ContextBlocks."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from services.trpg_memory.memory_models import MemoryItem, PinPolicy

from .canonical import estimate_tokens, normalize_content, sha256_text
from .models import BlockKind, CacheZone, ContextBlock, Stability

_PIN_TO_ZONE = {
    PinPolicy.GLOBAL_PREFIX: CacheZone.PREFIX,
    PinPolicy.CAMPAIGN_PREFIX: CacheZone.PREFIX,
    PinPolicy.CHAPTER_PREFIX: CacheZone.PREFIX,
    PinPolicy.SESSION_PREFIX: CacheZone.PINNED_MIDDLE,
    PinPolicy.SCENE_PREFIX: CacheZone.PINNED_MIDDLE,
    PinPolicy.DYNAMIC_RETRIEVAL_ONLY: CacheZone.DYNAMIC_TAIL,
}

_PIN_TO_STABILITY = {
    PinPolicy.GLOBAL_PREFIX: Stability.IMMUTABLE,
    PinPolicy.CAMPAIGN_PREFIX: Stability.IMMUTABLE,
    PinPolicy.CHAPTER_PREFIX: Stability.SESSION_PINNED,
    PinPolicy.SESSION_PREFIX: Stability.SESSION_PINNED,
    PinPolicy.SCENE_PREFIX: Stability.SCENE_PINNED,
    PinPolicy.DYNAMIC_RETRIEVAL_ONLY: Stability.TURN_DYNAMIC,
}


def memory_items_to_context_blocks(
    items: Iterable[MemoryItem],
    *,
    campaign_id: str,
    session_id: str | None = None,
    scene_id: str | None = None,
) -> tuple[ContextBlock, ...]:
    """Group pin-eligible memories into deterministic context blocks."""

    grouped: dict[tuple[PinPolicy, str, str | None], list[MemoryItem]] = defaultdict(list)
    for item in items:
        if item.pin_policy == PinPolicy.NEVER:
            continue
        zone = _PIN_TO_ZONE.get(item.pin_policy)
        if zone is None:
            continue
        owner = item.owner_id if item.visibility.value == "npc_private" else None
        grouped[(item.pin_policy, item.visibility.value, owner)].append(item)

    blocks: list[ContextBlock] = []
    for (pin_policy, visibility_value, owner_id), bucket in sorted(
        grouped.items(),
        key=lambda it: (it[0][0].value, it[0][1], it[0][2] or ""),
    ):
        bucket.sort(key=lambda item: (item.kind.value, item.text, item.memory_id))
        payload = {
            "pin_policy": pin_policy.value,
            "memories": [
                {
                    "memory_id": item.memory_id,
                    "kind": item.kind.value,
                    "text": item.text,
                    "truth_status": item.truth_status.value,
                    "subject_ids": list(item.subject_ids),
                    "owner_id": item.owner_id,
                    "source_turn_ids": list(item.source_turn_ids[-3:]),
                    "salience": item.salience,
                }
                for item in bucket
            ],
        }
        content_hash = sha256_text(normalize_content(payload))
        version = max(1, int(content_hash[:8], 16))
        scope_type = "campaign"
        scope_id = campaign_id
        if pin_policy == PinPolicy.SESSION_PREFIX:
            scope_type, scope_id = "session", session_id or campaign_id
        elif pin_policy == PinPolicy.SCENE_PREFIX:
            scope_type, scope_id = "scene", scene_id or session_id or campaign_id
        elif pin_policy == PinPolicy.CHAPTER_PREFIX:
            scope_type, scope_id = "chapter", campaign_id
        blocks.append(ContextBlock(
            block_id=f"memory.{campaign_id}.{pin_policy.value}.{visibility_value}.{owner_id or 'shared'}",
            kind=BlockKind.RETRIEVED_MEMORY,
            title=f"Pinned memories: {pin_policy.value}",
            content=payload,
            visibility=bucket[0].visibility,
            stability=_PIN_TO_STABILITY[pin_policy],
            cache_zone=_PIN_TO_ZONE[pin_policy],
            version=version,
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=scope_id,
            owner_id=owner_id,
            content_hash=content_hash,
            token_estimate=estimate_tokens(normalize_content(payload)),
            priority=70,
            tags=("memory_projection", pin_policy.value),
        ))
    return tuple(blocks)
