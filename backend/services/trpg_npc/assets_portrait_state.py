"""Portrait state mutations on ``memory_state.npcs`` rows.

Synchronous helpers that flip the ``portrait_auto_*`` fields, build the
portrait prompt, and look NPC rows up by key. The async generation
pipeline in ``assets_portrait_tasks`` imports from here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from orm.models import GameSession

from services.trpg_npc.assets_models import ModelRuntime

PORTRAIT_GENERATOR_VERSION = "media-generation-v1"


def _mark_portrait_requests(
    npcs: list[Any],
    avatar_model: ModelRuntime,
) -> list[str]:
    queued_at = datetime.now(timezone.utc).isoformat()
    queued: list[str] = []
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = str(npc.get("key") or npc.get("id") or "").strip()
        if not key or _has_portrait(npc):
            continue
        if not _has_portrait_seed(npc):
            continue
        status = str(npc.get("portrait_auto_status") or "").strip()
        version = str(npc.get("portrait_generator_version") or "").strip()
        if version == PORTRAIT_GENERATOR_VERSION and status in {
            "queued",
            "generating",
            "failed",
        }:
            continue
        npc["portrait_auto_requested_at"] = queued_at
        npc["portrait_auto_status"] = "queued"
        npc["portrait_auto_error"] = ""
        npc["portrait_model"] = avatar_model.model
        npc["portrait_model_provider"] = avatar_model.provider
        npc["portrait_generator_version"] = PORTRAIT_GENERATOR_VERSION
        queued.append(key)
    return queued


def _has_portrait(npc: dict[str, Any]) -> bool:
    return any(
        str(npc.get(field) or "").strip()
        for field in ("portrait_url", "avatar_url", "image_url", "image", "portrait")
    )


def _has_portrait_seed(npc: dict[str, Any]) -> bool:
    return any(
        str(npc.get(field) or "").strip()
        for field in (
            "portrait_prompt",
            "appearance",
            "summary",
            "description",
            "role",
            "name",
        )
    )


def _find_npc(session: GameSession, npc_key: str) -> dict[str, Any] | None:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return None
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if str(npc.get("key") or npc.get("id") or "").strip() == npc_key:
            return npc
    return None


def _mark_portrait_done(npc: dict[str, Any]) -> None:
    npc["portrait_auto_status"] = "done"
    npc["portrait_auto_error"] = ""
    npc["portrait_generator_version"] = PORTRAIT_GENERATOR_VERSION


def _mark_portrait_failed(npc: dict[str, Any], error: str) -> None:
    npc["portrait_auto_status"] = "failed"
    npc["portrait_auto_error"] = error[:300]
    npc["portrait_generator_version"] = PORTRAIT_GENERATOR_VERSION


def _build_portrait_prompt(npc: dict[str, Any], session: GameSession) -> str:
    existing = str(npc.get("portrait_prompt") or "").strip()
    if existing:
        return existing

    module_state = session.module_state if isinstance(session.module_state, dict) else {}
    context = {
        "name": npc.get("name"),
        "public_name": npc.get("player_known_name") or npc.get("public_name"),
        "gender": npc.get("gender"),
        "age": npc.get("age"),
        "role": npc.get("role"),
        "appearance": npc.get("appearance"),
        "summary": npc.get("summary") or npc.get("description"),
        "voice_hint": npc.get("voice_hint"),
        "scene": module_state.get("scene_name") or module_state.get("scene"),
        "module": module_state.get("title"),
    }
    compact = ", ".join(
        f"{k}: {v}" for k, v in context.items() if str(v or "").strip()
    )
    return (
        "Square TRPG NPC portrait, head-and-shoulders character art, clear face, "
        "setting-appropriate costume, expressive but natural lighting, no text, "
        f"no watermark. Character details: {compact}"
    )[:1800]
