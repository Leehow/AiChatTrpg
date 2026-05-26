"""NPC presentation assets for ChatRPG.

New NPCs should become renderable characters, not bare memory rows. This
module assigns stable TTS voices from the configured character-dialogue
model and queues portrait generation with the configured avatar model.

This file is the stable import facade; the implementation lives in
``assets_voice_pools``, ``assets_voice_assignment``, ``assets_models``,
``assets_portrait_state``, and ``assets_portrait_tasks``. Existing call
sites (and the debug smoke tests) keep importing from
``services.trpg_npc.assets`` directly, including the underscore helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession

from services.trpg_npc.assets_models import (
    ModelRuntime,
    _is_probable_image_model,
    _provider_default_base_url,
    _provider_default_key,
    _resolve_role_model,
)
from services.trpg_npc.assets_portrait_state import (
    PORTRAIT_GENERATOR_VERSION,
    _build_portrait_prompt,
    _find_npc,
    _has_portrait,
    _has_portrait_seed,
    _mark_portrait_done,
    _mark_portrait_failed,
    _mark_portrait_requests,
)
from services.trpg_npc.assets_portrait_tasks import (
    _INFLIGHT_PORTRAIT_TASKS,
    _generate_avatar_url,
    _generate_npc_portraits,
    _generate_single_npc_portrait,
    logger,
    spawn_npc_portrait_task,
)
from services.trpg_npc.assets_voice_assignment import (
    _assign_missing_voices,
    _effective_voice,
    _has_any,
    _keyword_voice,
    _stable_voice,
    _voice_compatible,
    _voice_match_text,
)
from services.trpg_npc.assets_voice_pools import (
    FEMALE_VOICES,
    GEMINI_FEMALE,
    GEMINI_MALE,
    MALE_VOICES,
    MINIMAX_FEMALE,
    MINIMAX_MALE,
    _FEMALE_HINT_RE,
    _MALE_HINT_RE,
    _gender_text,
    _is_female,
    _tts_provider_for_model,
    _voice_pools,
)

__all__ = [
    "FEMALE_VOICES",
    "GEMINI_FEMALE",
    "GEMINI_MALE",
    "MALE_VOICES",
    "MINIMAX_FEMALE",
    "MINIMAX_MALE",
    "ModelRuntime",
    "NpcAssetSummary",
    "PORTRAIT_GENERATOR_VERSION",
    "ensure_npc_assets",
    "spawn_npc_portrait_task",
]


@dataclass
class NpcAssetSummary:
    voices_assigned: int = 0
    portraits_queued: list[str] = field(default_factory=list)
    portrait_model: str = ""
    voice_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "voices_assigned": self.voices_assigned,
            "portraits_queued": list(self.portraits_queued),
            "portrait_model": self.portrait_model,
            "voice_model": self.voice_model,
        }


async def ensure_npc_assets(
    db: AsyncSession,
    session: GameSession,
    *,
    queue_portraits: bool = True,
) -> NpcAssetSummary:
    """Fill missing voice fields and queue portraits on ``memory_state.npcs``.

    The caller owns the surrounding transaction. If ``summary.portraits_queued``
    is non-empty, call ``spawn_npc_portrait_task`` after commit so the background
    task can read the queued rows from a fresh session.
    """
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list) or not npcs:
        return NpcAssetSummary()

    summary = NpcAssetSummary()
    changed = False

    voice_model = await _resolve_role_model(db, "dialogue")
    voice_model_name = voice_model.model if voice_model else "qwen3-tts-flash"
    summary.voice_model = voice_model_name
    voice_changed = _assign_missing_voices(npcs, voice_model_name)
    if voice_changed:
        summary.voices_assigned = voice_changed
        changed = True

    avatar_model = await _resolve_role_model(db, "avatar")
    if avatar_model:
        summary.portrait_model = avatar_model.model
    if (
        queue_portraits
        and avatar_model
        and _is_probable_image_model(avatar_model.model, avatar_model.provider)
    ):
        queued = _mark_portrait_requests(npcs, avatar_model)
        if queued:
            summary.portraits_queued = queued
            changed = True

    if changed:
        mem["npcs"] = npcs
        session.memory_state = mem
        flag_modified(session, "memory_state")
    return summary
