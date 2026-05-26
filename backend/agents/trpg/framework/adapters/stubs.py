"""No-op adapter implementations.

Used in tests and as defaults for projects that don't wire up a particular
capability (e.g. chatrpg has no TTS, so it injects NoOpMultimediaAdapter)."""

from __future__ import annotations

from datetime import datetime, timezone

from .protocols import (
    AudioRef,
    ImageRef,
    RetrievalHit,
)


class NoOpRetrievalAdapter:
    async def search(
        self,
        query: str,
        *,
        ruleset_id: str,
        module_id: str | None,
        top_k: int = 8,
    ) -> list[RetrievalHit]:
        return []


class NoOpMultimediaAdapter:
    async def synthesize_audio(self, text: str, voice: str) -> AudioRef | None:
        return None

    async def generate_portrait(self, prompt: str, npc_key: str) -> ImageRef | None:
        return None

    async def render_scene(self, scene_key: str, prompt: str) -> ImageRef | None:
        return None


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
