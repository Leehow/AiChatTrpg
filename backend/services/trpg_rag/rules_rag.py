"""Minimal rules RAG facade.

Rules RAG should be safe to explain to players after normal visibility checks.
This in-memory implementation is a placeholder for vector/full-text search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.trpg_context.models import ActorScope, Visibility
from .namespace_models import RagChunk, RagNamespace
from .rag_visibility_filter import filter_chunks_for_actor


@dataclass(frozen=True)
class RagSearchResult:
    chunk: RagChunk
    score: float


class InMemoryRulesRag:
    def __init__(self, chunks: tuple[RagChunk, ...] = ()) -> None:
        self.chunks = chunks

    def search(self, *, query: str, actor: ActorScope, limit: int = 3) -> tuple[RagSearchResult, ...]:
        candidates = [chunk for chunk in self.chunks if chunk.namespace == RagNamespace.RULES]
        visible = filter_chunks_for_actor(tuple(candidates), actor)
        scored = [(chunk, self._score(query, chunk.text)) for chunk in visible]
        scored = [(chunk, score) for chunk, score in scored if score > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return tuple(RagSearchResult(chunk=chunk, score=score) for chunk, score in scored[:limit])

    def _score(self, query: str, text: str) -> float:
        q = set(re.findall(r"[\w\u4e00-\u9fff]+", query.casefold()))
        t = set(re.findall(r"[\w\u4e00-\u9fff]+", text.casefold()))
        if not q or not t:
            return 0.0
        return len(q.intersection(t)) / len(q)


def public_rules_chunk(chunk_id: str, text: str, source_id: str) -> RagChunk:
    return RagChunk(
        chunk_id=chunk_id,
        namespace=RagNamespace.RULES,
        text=text,
        visibility=Visibility.PUBLIC,
        source_id=source_id,
    )
