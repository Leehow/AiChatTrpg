"""Visibility filtering for RAG chunks."""

from __future__ import annotations

from services.trpg_context.models import ActorScope, BlockKind, CacheZone, ContextBlock, Stability
from services.trpg_context.visibility import can_read
from .namespace_models import RagChunk


def can_read_chunk(chunk: RagChunk, actor: ActorScope) -> bool:
    block = ContextBlock(
        block_id=chunk.chunk_id,
        kind=BlockKind.RETRIEVED_MEMORY,
        title=chunk.source_id,
        content=chunk.text,
        visibility=chunk.visibility,
        owner_id=chunk.owner_id,
        stability=Stability.TURN_DYNAMIC,
        cache_zone=CacheZone.DYNAMIC_TAIL,
        scope_type="turn",
        scope_id="rag",
    )
    return can_read(block, actor)


def filter_chunks_for_actor(chunks: tuple[RagChunk, ...], actor: ActorScope) -> tuple[RagChunk, ...]:
    return tuple(chunk for chunk in chunks if can_read_chunk(chunk, actor))
