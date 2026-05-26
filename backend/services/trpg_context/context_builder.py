"""Cache-aware ContextBuilder.

This is the main entry point from trpg_scene_runtime.preprocess().
"""

from __future__ import annotations

from typing import Any, Sequence

from .cache_policy import sort_key
from .canonical import estimate_tokens, render_blocks, sha256_text
from .models import (
    BlockKind,
    CacheZone,
    ContextBlock,
    ContextRequest,
    CompiledContext,
    ContextProfile,
    Stability,
    Visibility,
)
from .visibility import can_read, visibility_signature
from .block_store import ContextBlockStore
from .world_state_projector import project_world_state


class ContextBuilder:
    def __init__(self, block_store: ContextBlockStore) -> None:
        self.block_store = block_store

    def build(self, request: ContextRequest) -> CompiledContext:
        actor = request.actor
        static_blocks = self.block_store.get_active_blocks(
            ruleset_id=request.ruleset_id,
            campaign_id=request.campaign_id,
            chapter_id=request.chapter_id,
            location_id=request.location_id,
            npc_ids=request.npc_ids_in_scene,
            session_id=actor.session_id,
            scene_id=actor.scene_id,
        )
        visible_static = [block for block in static_blocks if can_read(block, actor)]
        dynamic_blocks = self._dynamic_blocks(request)
        visible_dynamic = [block for block in dynamic_blocks if can_read(block, actor)]

        prefix_candidates = [
            block for block in visible_static if block.cache_zone == CacheZone.PREFIX
        ]
        pinned_candidates = [
            block for block in visible_static if block.cache_zone == CacheZone.PINNED_MIDDLE
        ]

        prefix_blocks = self._fit_blocks(
            sorted(prefix_candidates, key=sort_key),
            max_tokens=request.max_prefix_tokens,
        )
        pinned_blocks = self._fit_blocks(
            sorted(pinned_candidates, key=sort_key),
            max_tokens=max(1, request.max_dynamic_tokens // 3),
        )
        tail_blocks = self._fit_dynamic_blocks(
            sorted(visible_dynamic, key=sort_key),
            max_tokens=request.max_dynamic_tokens,
        )

        prefix_text = render_blocks(prefix_blocks)
        dynamic_text = render_blocks([*pinned_blocks, *tail_blocks])
        prefix_hash = sha256_text(prefix_text)
        vis_sig = visibility_signature(actor)
        cache_key = f"{request.provider.value}:{request.model}:{actor.cache_namespace()}:{vis_sig}:{prefix_hash[:16]}"

        return CompiledContext(
            prefix_blocks=tuple(prefix_blocks),
            pinned_blocks=tuple(pinned_blocks),
            dynamic_blocks=tuple(tail_blocks),
            prefix_text=prefix_text,
            dynamic_text=dynamic_text,
            prefix_hash=prefix_hash,
            visibility_signature=vis_sig,
            cache_key=cache_key,
            token_estimate=estimate_tokens(prefix_text) + estimate_tokens(dynamic_text),
        )

    def _fit_blocks(self, blocks: Sequence[ContextBlock], max_tokens: int) -> list[ContextBlock]:
        result: list[ContextBlock] = []
        used = 0
        for block in blocks:
            block_text = render_blocks([block])
            cost = block.token_estimate or estimate_tokens(block_text)
            if result and used + cost > max_tokens:
                continue
            result.append(block)
            used += cost
        return result

    def _fit_dynamic_blocks(self, blocks: Sequence[ContextBlock], max_tokens: int) -> list[ContextBlock]:
        required = {BlockKind.WORLD_STATE, BlockKind.CURRENT_INPUT}
        result: list[ContextBlock] = []
        used = 0
        for block in blocks:
            block_text = render_blocks([block])
            cost = block.token_estimate or estimate_tokens(block_text)
            if block.kind not in required and result and used + cost > max_tokens:
                continue
            result.append(block)
            used += cost
        return result

    def _dynamic_blocks(self, request: ContextRequest) -> list[ContextBlock]:
        dynamic = request.dynamic
        if dynamic is None:
            return []
        blocks: list[ContextBlock] = []

        world_payload: dict[str, Any] = {
            "turn_id": dynamic.turn_id,
            "world_state": project_world_state(dynamic.world_state, actor=request.actor),
            "actor_state": dynamic.actor_state,
            "dice_results": list(dynamic.dice_results),
        }

        live_visibility = Visibility.GM_ONLY
        live_owner_id = None
        if request.actor.profile == ContextProfile.PLAYER:
            live_visibility = Visibility.PARTY_KNOWN
        elif request.actor.profile == ContextProfile.NPC:
            live_visibility = Visibility.NPC_PRIVATE
            live_owner_id = request.actor.npc_id

        blocks.append(
            ContextBlock(
                block_id=f"turn.{dynamic.turn_id}.world_state",
                kind=BlockKind.WORLD_STATE,
                title="Authoritative live world state for this turn",
                content=world_payload,
                visibility=live_visibility,
                owner_id=live_owner_id,
                stability=Stability.TURN_DYNAMIC,
                cache_zone=CacheZone.DYNAMIC_TAIL,
                scope_type="turn",
                scope_id=dynamic.turn_id,
                priority=100,
            )
        )

        if dynamic.retrieved_memories:
            memory_visibility = Visibility.GM_ONLY
            memory_owner_id = None
            if request.actor.profile == ContextProfile.NPC:
                memory_visibility = Visibility.NPC_PRIVATE
                memory_owner_id = request.actor.npc_id
            elif request.actor.profile == ContextProfile.PLAYER:
                memory_visibility = Visibility.PARTY_KNOWN
            blocks.append(
                ContextBlock(
                    block_id=f"turn.{dynamic.turn_id}.retrieved_memory",
                    kind=BlockKind.RETRIEVED_MEMORY,
                    title="Retrieved episodic memories relevant to the current action",
                    content={"memories": list(dynamic.retrieved_memories)},
                    visibility=memory_visibility,
                    owner_id=memory_owner_id,
                    stability=Stability.TURN_DYNAMIC,
                    cache_zone=CacheZone.DYNAMIC_TAIL,
                    scope_type="turn",
                    scope_id=dynamic.turn_id,
                    priority=80,
                )
            )

        observed_visibility = Visibility.PARTY_KNOWN
        observed_owner_id = None
        if request.actor.profile == ContextProfile.NPC:
            observed_visibility = Visibility.NPC_PRIVATE
            observed_owner_id = request.actor.npc_id

        if dynamic.recent_transcript:
            blocks.append(
                ContextBlock(
                    block_id=f"turn.{dynamic.turn_id}.recent_transcript",
                    kind=BlockKind.RECENT_TRANSCRIPT,
                    title="Recent transcript observed in the current scene",
                    content={"messages": list(dynamic.recent_transcript)},
                    visibility=observed_visibility,
                    owner_id=observed_owner_id,
                    stability=Stability.TURN_DYNAMIC,
                    cache_zone=CacheZone.DYNAMIC_TAIL,
                    scope_type="turn",
                    scope_id=dynamic.turn_id,
                    priority=60,
                )
            )

        blocks.append(
            ContextBlock(
                block_id=f"turn.{dynamic.turn_id}.current_input",
                kind=BlockKind.CURRENT_INPUT,
                title="Current player input observed in the current scene",
                content={"text": dynamic.current_input},
                visibility=observed_visibility,
                owner_id=observed_owner_id,
                stability=Stability.TURN_DYNAMIC,
                cache_zone=CacheZone.DYNAMIC_TAIL,
                scope_type="turn",
                scope_id=dynamic.turn_id,
                priority=100,
            )
        )
        return blocks
