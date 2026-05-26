"""Async portrait generation queue for NPC assets.

Owns the fire-and-forget portrait task spawned from
``ensure_npc_assets`` callers, the per-NPC generation step, and the
avatar URL renderer that talks to ``services.media_generation``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from core.database import get_session_factory
from orm.models import GameSession
from services.media_generation import (
    MediaModelRuntime,
    avatar_image_size_for,
    generate_image,
)
from services.media_storage import store_image_reference

from services.trpg_npc.assets_models import (
    ModelRuntime,
    _is_probable_image_model,
    _resolve_role_model,
)
from services.trpg_npc.assets_portrait_state import (
    _build_portrait_prompt,
    _find_npc,
    _has_portrait,
    _mark_portrait_done,
    _mark_portrait_failed,
)

logger = logging.getLogger("chatrpg.trpg.npc_assets")

_INFLIGHT_PORTRAIT_TASKS: set[asyncio.Task] = set()


def spawn_npc_portrait_task(
    session_id: str,
    user_id: str,
    npc_keys: list[str],
    *,
    message_id: str = "",
) -> asyncio.Task | None:
    keys = [str(k).strip() for k in npc_keys if str(k).strip()]
    if not keys:
        return None
    task = asyncio.create_task(
        _generate_npc_portraits(session_id, user_id, keys, message_id=message_id)
    )
    _INFLIGHT_PORTRAIT_TASKS.add(task)
    task.add_done_callback(_INFLIGHT_PORTRAIT_TASKS.discard)
    return task


async def _generate_npc_portraits(
    session_id: str,
    user_id: str,
    npc_keys: list[str],
    *,
    message_id: str = "",
) -> None:
    from services.trpg_postprocess_steps import step_timer

    # Snapshot the configured avatar model name up-front so the step
    # detail surfaces what's running, even if some per-NPC calls fail
    # before reaching the model. The per-NPC path resolves again on
    # demand so a mid-run admin change still takes effect.
    model_name = "?"
    try:
        factory = get_session_factory()
        async with factory() as db:
            avatar_model = await _resolve_role_model(db, "avatar")
            if avatar_model is not None:
                model_name = str(avatar_model.model or "?")
    except Exception:  # noqa: BLE001 - cosmetic
        pass

    async with step_timer(message_id, "portrait_generation") as handle:
        succeeded = 0
        failed = 0
        for key in npc_keys:
            try:
                await _generate_single_npc_portrait(session_id, user_id, key)
                succeeded += 1
            except Exception:
                failed += 1
                logger.warning(
                    "auto NPC portrait failed: session=%s npc=%s",
                    session_id,
                    key,
                    exc_info=True,
                )
        handle["detail"] = (
            f"{model_name} | {succeeded}/{len(npc_keys)} done"
            + (f", {failed} failed" if failed else "")
        )


async def _generate_single_npc_portrait(
    session_id: str,
    user_id: str,
    npc_key: str,
) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    factory = get_session_factory()
    async with factory() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.user_id != user_id:
            return
        npc = _find_npc(session, npc_key)
        if npc is None:
            return
        if _has_portrait(npc):
            _mark_portrait_done(npc)
            flag_modified(session, "memory_state")
            await db.commit()
            return

        model = await _resolve_role_model(db, "avatar")
        if model is None:
            _mark_portrait_failed(npc, "No avatar generation model configured")
            flag_modified(session, "memory_state")
            await db.commit()
            return
        if not _is_probable_image_model(model.model, model.provider):
            _mark_portrait_failed(
                npc,
                f"Avatar model '{model.model}' does not look image-capable",
            )
            flag_modified(session, "memory_state")
            await db.commit()
            return

        prompt = _build_portrait_prompt(npc, session)
        try:
            url = await _generate_avatar_url(model, prompt)
        except Exception as exc:
            _mark_portrait_failed(npc, f"{type(exc).__name__}: {exc}")
            flag_modified(session, "memory_state")
            await db.commit()
            raise

        if not url:
            _mark_portrait_failed(npc, "avatar model returned no image")
        else:
            now = datetime.now(timezone.utc).isoformat()
            npc["portrait_url"] = url
            npc["avatar_url"] = url
            npc["portrait_thumbnail_url"] = url
            npc["portrait_prompt"] = prompt
            npc["portrait_model"] = model.model
            npc["portrait_model_provider"] = model.provider
            npc["portrait_generated_at"] = now
            _mark_portrait_done(npc)
        flag_modified(session, "memory_state")
        await db.commit()


async def _generate_avatar_url(model: ModelRuntime, prompt: str) -> str:
    if model.provider == "mock":
        return ""
    if not model.api_key or not model.base_url:
        raise RuntimeError(f"Avatar model '{model.provider}:{model.model}' is not configured")

    result = await generate_image(
        MediaModelRuntime(
            provider=model.provider,
            model=model.model,
            api_key=model.api_key,
            base_url=model.base_url,
        ),
        prompt=prompt,
        size=avatar_image_size_for(model.provider, model.model),
        n=1,
    )
    reference = result.primary_reference
    if not reference:
        return ""
    # Persist the binary so the database holds a stable URL instead of
    # inflating session rows with megabytes of base64. This also lets the
    # browser load portraits with a normal <img src> request.
    try:
        return await store_image_reference(reference)
    except ValueError as exc:
        logger.warning("avatar storage failed, falling back to inline: %s", exc)
        return reference
