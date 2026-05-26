"""Cache-aware block policy.

The policy deliberately favors stable, reusable material at the front and
moves mutable state to the dynamic tail.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BlockKind, CacheZone, ContextBlock, Stability, Visibility


PREFIX_ORDER: dict[BlockKind, int] = {
    BlockKind.ENGINE_PROTOCOL: 10,
    BlockKind.OUTPUT_SCHEMA: 20,
    BlockKind.TOOL_PROTOCOL: 30,
    BlockKind.RULESET_STATIC: 40,
    BlockKind.CAMPAIGN_STATIC: 50,
    BlockKind.CHAPTER_STATIC: 60,
    BlockKind.LOCATION_STATIC: 70,
    BlockKind.NPC_STATIC: 80,
    BlockKind.SESSION_SUMMARY: 90,
    BlockKind.SCENE_STATIC: 100,
}

DYNAMIC_ORDER: dict[BlockKind, int] = {
    BlockKind.WORLD_STATE: 10,
    BlockKind.RETRIEVED_MEMORY: 20,
    BlockKind.RECENT_TRANSCRIPT: 30,
    BlockKind.CURRENT_INPUT: 40,
}


@dataclass(frozen=True)
class PinInputs:
    salience: float
    expected_reuse_turns: float
    stability_score: float
    authority_score: float
    token_cost: float
    mutation_risk: float
    spoiler_risk: float


def pin_score(inputs: PinInputs) -> float:
    """Score a memory/context candidate for prefix pinning.

    Scores above ~0.65 are good pin candidates. Use this for memory-derived
    blocks, not for core protocol/rules blocks which should be configured.
    """
    return (
        inputs.salience * 0.30
        + inputs.expected_reuse_turns * 0.25
        + inputs.stability_score * 0.25
        + inputs.authority_score * 0.10
        - inputs.token_cost * 0.10
        - inputs.mutation_risk * 0.30
        - inputs.spoiler_risk * 0.40
    )


def default_cache_zone(kind: BlockKind, stability: Stability) -> CacheZone:
    if stability in {Stability.IMMUTABLE, Stability.SESSION_PINNED, Stability.SCENE_PINNED}:
        if kind in PREFIX_ORDER:
            return CacheZone.PREFIX
        return CacheZone.PINNED_MIDDLE
    if stability == Stability.TURN_DYNAMIC:
        return CacheZone.DYNAMIC_TAIL
    return CacheZone.NEVER


def sort_key(block: ContextBlock) -> tuple[int, int, str, int]:
    if block.cache_zone in {CacheZone.PREFIX, CacheZone.PINNED_MIDDLE}:
        kind_order = PREFIX_ORDER.get(block.kind, 999)
    else:
        kind_order = DYNAMIC_ORDER.get(block.kind, 999)
    # Never sort by content or retrieval score inside prefix. Use configured
    # priority, kind, scope, and id only.
    return (kind_order, -block.priority, block.block_id, block.version)


def spoiler_risk_for_visibility(visibility: Visibility) -> float:
    if visibility == Visibility.GM_ONLY:
        return 0.75
    if visibility == Visibility.NPC_PRIVATE:
        return 0.65
    if visibility == Visibility.SYSTEM_INTERNAL:
        return 1.0
    return 0.10
