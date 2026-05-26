"""Scenario RAG facade.

Scenario chunks may contain secrets. Always filter by ActorScope before adding
results to a prompt. Player-facing rule answers should not search this namespace
unless the calling profile is allowed to see module truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.trpg_context.models import ActorScope
from .namespace_models import RagChunk, RagNamespace
from .rag_visibility_filter import filter_chunks_for_actor
from .rules_rag import InMemoryRulesRag, RagSearchResult


@dataclass(frozen=True)
class ScenarioRagConfig:
    allow_player_scenario_search: bool = False


class InMemoryScenarioRag(InMemoryRulesRag):
    def __init__(self, chunks: tuple[RagChunk, ...] = (), config: ScenarioRagConfig | None = None) -> None:
        super().__init__(chunks)
        self.config = config or ScenarioRagConfig()

    def search(self, *, query: str, actor: ActorScope, limit: int = 5) -> tuple[RagSearchResult, ...]:
        if actor.profile.value == "player" and not self.config.allow_player_scenario_search:
            return ()
        candidates = [chunk for chunk in self.chunks if chunk.namespace == RagNamespace.SCENARIO]
        visible = filter_chunks_for_actor(tuple(candidates), actor)
        scored = [(chunk, self._score(query, chunk.text)) for chunk in visible]
        scored = [(chunk, score) for chunk, score in scored if score > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return tuple(RagSearchResult(chunk=chunk, score=score) for chunk, score in scored[:limit])
