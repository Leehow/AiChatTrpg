"""Adapter Protocols — the seam between framework and project-specific code.

The framework only depends on these interfaces. chatlab and chatrpg each
plug in their own concrete implementations (real DB, real OSS, real TTS for
chatlab; NoOp stubs + parsed_v6 direct slicing for chatrpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..models import (
    CharacterTemplate,
    LayeredPrompt,
    Message,
    ModelConfig,
    PromptMessage,
    RulesetData,
    SessionState,
    StableText,
)
from ..modes import Mode


@dataclass
class LlmDelta:
    delta: str
    is_final: bool = False
    raw: dict[str, Any] | None = None


@dataclass
class RetrievalHit:
    text: str
    score: float
    source: str = ""
    metadata: dict[str, Any] | None = None


@dataclass
class AudioRef:
    url: str
    duration_seconds: float = 0.0


@dataclass
class ImageRef:
    url: str
    width: int = 0
    height: int = 0


@runtime_checkable
class LlmAdapter(Protocol):
    async def stream_chat(
        self,
        messages: list[PromptMessage],
        *,
        model: ModelConfig,
        layered_prompt: LayeredPrompt | None = None,
    ) -> AsyncIterator[LlmDelta]:
        """Stream the LLM reply.

        Implementations may use `layered_prompt` (when supplied) to route
        through provider-specific cache-aware paths instead of the flat
        `messages` shape. `messages` always reflects the same content as a
        single-system fallback so adapters without cache support keep
        working unchanged."""
        ...


@runtime_checkable
class RulesetAdapter(Protocol):
    """Slices a RulesetData (and optionally a SessionState) into framework
    inputs. chatlab impl reads pre-distilled session fields; chatrpg impl
    slices ruleset.parsed_v6. Either way the framework only sees StableText."""

    def get_stable_text(
        self, ruleset: RulesetData, state: SessionState, mode: Mode,
    ) -> StableText: ...

    def get_chargen_pack(
        self, ruleset: RulesetData, state: SessionState,
    ) -> str: ...

    def get_character_template(
        self, ruleset: RulesetData, state: SessionState,
    ) -> CharacterTemplate: ...

    def get_guide_variable_text(
        self,
        ruleset: RulesetData,
        state: SessionState,
        *,
        message: str | None,
        recent_history: list[Message],
    ) -> str:
        """Per-turn guide-mode nudges. chatlab impl mirrors the existing
        build_guide_variable_rules (arc lookup + variation rules + culture
        rules). chatrpg impl returns "" by default."""
        ...


@runtime_checkable
class RetrievalAdapter(Protocol):
    async def search(
        self,
        query: str,
        *,
        ruleset_id: str,
        module_id: str | None,
        top_k: int = 8,
    ) -> list[RetrievalHit]:
        ...


@runtime_checkable
class MultimediaAdapter(Protocol):
    async def synthesize_audio(self, text: str, voice: str) -> AudioRef | None: ...

    async def generate_portrait(self, prompt: str, npc_key: str) -> ImageRef | None: ...

    async def render_scene(self, scene_key: str, prompt: str) -> ImageRef | None: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...
