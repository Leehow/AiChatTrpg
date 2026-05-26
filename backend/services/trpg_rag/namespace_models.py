"""RAG chunk models for separating rules, scenario, graph, and memory search."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from services.trpg_context.models import Visibility


class RagNamespace(str, Enum):
    RULES = "rules_rag"
    SCENARIO = "scenario_rag"
    CAMPAIGN_GRAPH = "campaign_graph"
    MEMORY = "memory_rag"


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    namespace: RagNamespace
    text: str
    visibility: Visibility
    source_id: str
    source_page: int | None = None
    owner_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
