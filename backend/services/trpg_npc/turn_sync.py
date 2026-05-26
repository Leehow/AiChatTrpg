"""Per-turn NPC text sync.

Runs after the GM finishes writing a reply. One LLM call reads the
whole turn (what the player said + how the GM responded + every NPC's
current state) and outputs text polish / action-summary deltas.

NPC Runtime V2 is the canonical state authority for mood vectors,
relationships, and memories. This legacy sync now stays as a compatibility
layer for prompt-facing prose fields: ``inner_state.emotional_state``,
``inner_state.motivation``, name visibility, and ``action_summary``. For NPCs
with ``runtime_state_v2`` it does not mutate interest/relationship state, and
it skips writes entirely when a newer V2 state_version has landed.

Output shape from the model::

    {
      "npc_updates": [
        {
          "key": "vern",
          "emotional_state": "wary, less hostile",
          "motivation": "wants to know why the PC is asking about Abattoir",
          "interest_delta": 1,
          "name_revealed": false,
          "new_action_event": "Vern lowered his rifle when the PC offered cash."
        }
      ]
    }

The runner applies each update through ``NpcAgent`` so visibility,
psychology, and action_summary stay normalised.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

# ``call_llm_json_task`` is rebound on this module by
# debug/trpg/test_memory_runtime_p6.py — keep the import here so the
# in-function call resolves through ``turn_sync`` globals.
from agents.trpg.llm_json import call_llm_json_task
from core.database import get_session_factory
from orm.models import GameSession
from services.trpg_npc.knowledge_runtime import (
    build_npc_knowledge_runtime,
    leak_warnings_to_dict,
)
from services.trpg_npc.turn_sync_apply import (
    _apply_interest_delta,
    _apply_name_claim,
    _audit_update_memory_leaks,
    _has_runtime_v2,
    _is_stale_v2_update,
    _mark_v2_projection,
    _parse_updates,
    _runtime_state_version,
)
from services.trpg_npc.turn_sync_prompt import (
    _MAX_NPCS_IN_PROMPT,
    _SYSTEM_PROMPT,
    _build_user_message,
    _current_scene_id,
    _split_in_scene,
)


logger = logging.getLogger("chatrpg.trpg_npc.turn_sync")

_INFLIGHT: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def spawn_turn_sync_task(
    session_id: str,
    user_id: str,
    *,
    player_text: str,
    gm_reply: str,
    based_on_turn_id: int | None = None,
    npc_state_versions: dict[str, int] | None = None,
    message_id: str = "",
) -> asyncio.Task:
    """Fire-and-forget background task. Player doesn't wait."""
    task = asyncio.create_task(
        _run_turn_sync(
            session_id=session_id,
            user_id=user_id,
            player_text=player_text,
            gm_reply=gm_reply,
            based_on_turn_id=based_on_turn_id,
            npc_state_versions=dict(npc_state_versions or {}),
            message_id=message_id,
        )
    )
    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)
    return task


async def sync_npcs_after_turn(
    db: Any,
    session: GameSession,
    *,
    player_text: str,
    gm_reply: str,
    cfg: dict[str, Any],
    based_on_turn_id: int | None = None,
    npc_state_versions: dict[str, int] | None = None,
) -> dict[str, int]:
    """Run the LLM, apply text deltas through ``NpcAgent``. Caller commits.

    Returns a tally of how many NPCs were touched and how. Most callers
    want the fire-and-forget ``spawn_turn_sync_task`` instead — this
    function is the synchronous core, exposed for tests + manual runs.
    """
    summary = {
        "considered": 0,
        "updated": 0,
        "text_polished": 0,
        "action_summary_updated": 0,
        "interest_changed": 0,
        "interest_skipped_v2": 0,
        "name_revealed": 0,
        "name_claim_recorded": 0,
        "stale_skipped": 0,
        "skipped": 0,
        "knowledge_profile_count": 0,
        "knowledge_leak_warnings": 0,
        "knowledge_leak_blocked": 0,
    }
    if not (cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")):
        summary["skipped"] = 1
        return summary

    npcs = (session.memory_state or {}).get("npcs") or []
    npcs = [n for n in npcs if isinstance(n, dict) and n.get("key")]
    if not npcs:
        return summary

    # In-scene NPCs first; if there are still many, cap the rest. Avoids
    # bloating the prompt for sessions where dozens of NPCs exist.
    in_scene, off_scene = _split_in_scene(npcs, session)
    selected = in_scene + off_scene
    selected = selected[:_MAX_NPCS_IN_PROMPT]
    summary["considered"] = len(selected)

    scene_id = _current_scene_id(session)
    knowledge_runtime = await build_npc_knowledge_runtime(
        db,
        session,
        npc_ids=[str(npc.get("key") or "") for npc in selected],
        scene_id=scene_id,
    )
    summary["knowledge_profile_count"] = len(knowledge_runtime.profiles_by_npc_id)

    user_message = _build_user_message(
        player_text,
        gm_reply,
        selected,
        session,
        knowledge_profiles_by_npc_id=knowledge_runtime.prompt_payloads_by_npc_id(),
    )

    try:
        raw = await call_llm_json_task(
            stage="npc_turn_sync",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            system_prefix=_SYSTEM_PROMPT,
            user_message=user_message,
            stream=False,
        )
    except Exception:
        logger.warning(
            "[chatrpg.trpg_npc.turn_sync] LLM call failed", exc_info=True,
        )
        summary["skipped"] += 1
        return summary

    updates = _parse_updates(raw)
    if not updates:
        return summary

    from services.trpg_npc import NpcAgent

    agent = NpcAgent(session)
    expected_versions = dict(npc_state_versions or {})
    for update in updates:
        if not isinstance(update, dict):
            continue
        key = str(update.get("key") or "").strip()
        npc = agent.get(key) if key else None
        if not key or npc is None:
            continue
        leaks = _audit_update_memory_leaks(
            update,
            knowledge_runtime.forbidden_memories_by_npc_id.get(key) or (),
        )
        if leaks:
            summary["knowledge_leak_warnings"] += len(leaks)
            summary["knowledge_leak_blocked"] += 1
            logger.info(
                "[chatrpg.trpg_npc.turn_sync] blocked leaking update npc_id=%s warnings=%s",
                key,
                leak_warnings_to_dict(leaks),
            )
            continue
        runtime_v2 = _has_runtime_v2(npc)
        if runtime_v2 and _is_stale_v2_update(npc, key, expected_versions):
            summary["stale_skipped"] += 1
            continue

        inner_changes: dict[str, Any] = {}
        emotion = str(update.get("emotional_state") or "").strip()
        if emotion:
            inner_changes["emotional_state"] = emotion
        motivation = str(update.get("motivation") or "").strip()
        if motivation:
            inner_changes["motivation"] = motivation
        if inner_changes:
            # V2 owns numeric mood and relationships; these legacy fields are
            # now prompt-facing prose projections. Deep-merge so thought_log
            # and secret_agenda survive.
            agent.update(key, inner_state=inner_changes)
            summary["updated"] += 1
            if runtime_v2:
                summary["text_polished"] += 1
                _mark_v2_projection(
                    agent,
                    key,
                    based_on_turn_id=based_on_turn_id,
                    state_version=_runtime_state_version(npc),
                )

        delta_raw = update.get("interest_delta")
        try:
            delta = int(delta_raw) if delta_raw is not None else 0
        except (TypeError, ValueError):
            delta = 0
        if delta:
            if runtime_v2:
                summary["interest_skipped_v2"] += 1
            else:
                _apply_interest_delta(agent, key, delta)
                summary["interest_changed"] += 1

        if update.get("name_revealed") is True:
            if agent.reveal_name(key):
                summary["name_revealed"] += 1

        claim = update.get("name_claim")
        if isinstance(claim, dict):
            if _apply_name_claim(agent, key, claim):
                summary["name_claim_recorded"] += 1

        event = str(update.get("new_action_event") or "").strip()
        if event:
            if await agent.update_action_summary(key, event, cfg=cfg):
                summary["action_summary_updated"] += 1
                if runtime_v2:
                    _mark_v2_projection(
                        agent,
                        key,
                        based_on_turn_id=based_on_turn_id,
                        state_version=_runtime_state_version(npc),
                    )

    if agent.is_dirty():
        try:
            flag_modified(session, "memory_state")
        except Exception:
            pass
    return summary


def collect_runtime_state_versions(session: GameSession) -> dict[str, int]:
    """Snapshot current V2 state versions for stale background guards."""

    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return {}
    versions: dict[str, int] = {}
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = str(npc.get("key") or "").strip()
        if key and _has_runtime_v2(npc):
            versions[key] = _runtime_state_version(npc)
    return versions


# ---------------------------------------------------------------------------
# Internal: background task
# ---------------------------------------------------------------------------


async def _run_turn_sync(
    *,
    session_id: str,
    user_id: str,
    player_text: str,
    gm_reply: str,
    based_on_turn_id: int | None = None,
    npc_state_versions: dict[str, int] | None = None,
    message_id: str = "",
) -> None:
    from services.trpg_postprocess_steps import step_timer

    factory = get_session_factory()
    async with step_timer(message_id, "npc_text_sync") as handle:
        try:
            async with factory() as db:
                session = await db.get(GameSession, session_id)
                if session is None or session.user_id != user_id:
                    handle["detail"] = "skipped: session missing"
                    return
                from routes.rulesets import _resolve_default_compiler_config

                cfg = await _resolve_default_compiler_config(db)
                summary = await sync_npcs_after_turn(
                    db,
                    session,
                    player_text=player_text,
                    gm_reply=gm_reply,
                    cfg=cfg,
                    based_on_turn_id=based_on_turn_id,
                    npc_state_versions=dict(npc_state_versions or {}),
                )
                await db.commit()
                logger.info(
                    "[chatrpg.trpg_npc.turn_sync] session=%s summary=%s",
                    session_id, summary,
                )
                model_name = str(cfg.get("model") or "?")
                handle["detail"] = (
                    f"{model_name} | "
                    f"updated={summary.get('updated', 0)} "
                    f"reveals={summary.get('name_revealed', 0)} "
                    f"claims={summary.get('name_claim_recorded', 0)}"
                )
        except Exception as exc:
            logger.warning(
                "[chatrpg.trpg_npc.turn_sync] background task crashed for session %s",
                session_id, exc_info=True,
            )
            handle["detail"] = f"error: {type(exc).__name__}"
