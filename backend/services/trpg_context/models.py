"""Context and cache-aware memory models for chatrpg.

This module intentionally uses stdlib dataclasses so it can be introduced
without forcing a Pydantic v1/v2 decision. FastAPI routes can wrap these with
Pydantic DTOs later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence


class Visibility(str, Enum):
    PUBLIC = "public"
    PARTY_KNOWN = "party_known"
    GM_ONLY = "gm_only"
    NPC_PRIVATE = "npc_private"
    SYSTEM_INTERNAL = "system_internal"


class ContextProfile(str, Enum):
    GM = "gm"
    PLAYER = "player"
    NPC = "npc"
    MEMORY_EXTRACTOR = "memory_extractor"
    RULE_ADJUDICATOR = "rule_adjudicator"


class Stability(str, Enum):
    IMMUTABLE = "immutable"
    SESSION_PINNED = "session_pinned"
    SCENE_PINNED = "scene_pinned"
    TURN_DYNAMIC = "turn_dynamic"


class CacheZone(str, Enum):
    PREFIX = "prefix"
    PINNED_MIDDLE = "pinned_middle"
    DYNAMIC_TAIL = "dynamic_tail"
    NEVER = "never"


class BlockKind(str, Enum):
    ENGINE_PROTOCOL = "engine_protocol"
    OUTPUT_SCHEMA = "output_schema"
    TOOL_PROTOCOL = "tool_protocol"
    RULESET_STATIC = "ruleset_static"
    CAMPAIGN_STATIC = "campaign_static"
    CHAPTER_STATIC = "chapter_static"
    LOCATION_STATIC = "location_static"
    NPC_STATIC = "npc_static"
    SESSION_SUMMARY = "session_summary"
    SCENE_STATIC = "scene_static"
    WORLD_STATE = "world_state"
    RETRIEVED_MEMORY = "retrieved_memory"
    RECENT_TRANSCRIPT = "recent_transcript"
    CURRENT_INPUT = "current_input"


class Provider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    LOCAL = "local"


@dataclass(frozen=True)
class ActorScope:
    """Who the prompt is being built for."""

    profile: ContextProfile
    campaign_id: str
    session_id: str | None = None
    scene_id: str | None = None
    npc_id: str | None = None
    party_id: str | None = None

    def cache_namespace(self) -> str:
        npc_part = self.npc_id or "none"
        scene_part = self.scene_id or "none"
        session_part = self.session_id or "none"
        return f"{self.profile.value}:{self.campaign_id}:{session_part}:{scene_part}:{npc_part}"


@dataclass(frozen=True)
class ContextBlock:
    """A versioned prompt block.

    A ContextBlock is not just text. It carries cache, stability, and visibility
    metadata, so the compiler can place it in the correct part of the prompt.
    """

    block_id: str
    kind: BlockKind
    title: str
    content: Mapping[str, Any] | str
    visibility: Visibility
    stability: Stability
    cache_zone: CacheZone
    version: int = 1
    scope_type: Literal["global", "ruleset", "campaign", "chapter", "location", "npc", "session", "scene", "turn"] = "global"
    scope_id: str = "global"
    owner_id: str | None = None
    content_hash: str | None = None
    token_estimate: int | None = None
    priority: int = 50
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def versioned_id(self) -> str:
        return f"{self.block_id}.v{self.version}"


@dataclass(frozen=True)
class DynamicContext:
    """Per-turn values that must stay near the end of the prompt."""

    turn_id: str
    world_state: Mapping[str, Any] = field(default_factory=dict)
    actor_state: Mapping[str, Any] = field(default_factory=dict)
    retrieved_memories: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    recent_transcript: Sequence[Mapping[str, str]] = field(default_factory=tuple)
    current_input: str = ""
    dice_results: Sequence[Mapping[str, Any]] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextRequest:
    actor: ActorScope
    provider: Provider
    model: str
    ruleset_id: str
    campaign_id: str
    chapter_id: str | None = None
    location_id: str | None = None
    npc_ids_in_scene: tuple[str, ...] = field(default_factory=tuple)
    dynamic: DynamicContext | None = None
    max_prefix_tokens: int = 16_000
    max_dynamic_tokens: int = 12_000


@dataclass(frozen=True)
class CompiledContext:
    prefix_blocks: tuple[ContextBlock, ...]
    pinned_blocks: tuple[ContextBlock, ...]
    dynamic_blocks: tuple[ContextBlock, ...]
    prefix_text: str
    dynamic_text: str
    prefix_hash: str
    visibility_signature: str
    cache_key: str
    token_estimate: int


@dataclass(frozen=True)
class ProviderPrompt:
    """Provider-agnostic output of PromptCompiler.

    The API adapter can translate this object into the exact SDK call shape.
    """

    provider: Provider
    model: str
    payload: Mapping[str, Any]
    cache_key: str
    prefix_hash: str
    block_version_ids: tuple[str, ...]
