"""Best-effort NPC work that runs after the visible GM reply is saved."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from core.database import get_session_factory
from orm.models import GameSession
from services.trpg_npc.background_planner import spawn_background_npc_planner_task
from services.trpg_npc.liveness.routine_planner import RoutinePlanner
from services.trpg_npc.runtime_adapter import warm_npc_action_board_after_turn
from services.trpg_npc.runtime_persistence import persist_npc_runtime_v2_tables_authority
from services.trpg_postprocess_steps import (
    record_step_standalone,
    step_timer_with_db,
)

logger = logging.getLogger("chatrpg.trpg_npc.post_visible")
_INFLIGHT: set[asyncio.Task] = set()


def spawn_npc_post_visible_work(
    *,
    session_id: str,
    user_id: str,
    player_text: str,
    gm_reply: str,
    turn_id: int,
    structured_events: list[Any] | None = None,
    message_id: str = "",
) -> asyncio.Task:
    """Schedule non-visible NPC runtime work without blocking the IC turn.

    ``message_id`` threads the assistant message id into per-step
    progress recording so the frontend can poll
    ``GET /api/sessions/.../messages/<id>/postprocess-steps``.
    """

    task = asyncio.create_task(
        run_npc_post_visible_work(
            session_id=session_id,
            user_id=user_id,
            player_text=player_text,
            gm_reply=gm_reply,
            turn_id=turn_id,
            structured_events=structured_events,
            message_id=message_id,
        )
    )
    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)
    return task


async def run_npc_post_visible_work(
    *,
    session_id: str,
    user_id: str,
    player_text: str,
    gm_reply: str,
    turn_id: int,
    structured_events: list[Any] | None = None,
    message_id: str = "",
) -> dict[str, Any]:
    """Warm next-turn NPC runtime state after the user-visible response.

    Awaits its own grandchild tasks (turn_sync + background_planner) so
    a single ``await`` on the returned ``asyncio.Task`` from the IC
    runner represents *all* post-visible NPC work being settled. The
    finaliser that emits ``phase3_complete`` relies on this to time the
    overall phase correctly.
    """

    summary: dict[str, Any] = {
        "mode": "post_visible_npc_work",
        "turn_id": int(turn_id or 0),
        "status": "started",
    }
    factory = get_session_factory()
    try:
        async with factory() as db:
            session = await db.get(GameSession, session_id)
            if session is None or str(session.user_id) != str(user_id):
                summary["status"] = "skipped"
                summary["skipped"] = "missing_or_wrong_user_session"
                return summary

            async with step_timer_with_db(
                db, message_id, "action_board_warm"
            ) as handle:
                warm = warm_npc_action_board_after_turn(
                    session,
                    player_text=player_text,
                    gm_reply=gm_reply,
                    turn_id=turn_id,
                    structured_events=structured_events,
                    write_json_snapshot=False,
                )
                summary["warm"] = warm.to_dict()
                handle["detail"] = (
                    f"npcs={warm.active_npc_count} cards={warm.stored_card_count}"
                )

            if not warm.error and warm.action_board is not None:
                async with step_timer_with_db(
                    db, message_id, "runtime_state_persist"
                ) as handle:
                    summary["table_authority"] = await persist_npc_runtime_v2_tables_authority(
                        db, session, warm,
                    )
                    handle["detail"] = "tables synced"

            async with step_timer_with_db(
                db, message_id, "routine_events"
            ) as handle:
                events_planned = _plan_routine_events(session)
                summary["routine_events"] = [event.to_dict() for event in events_planned]
                handle["detail"] = f"{len(events_planned)} events"

            summary["background_planner_spawned"] = True
            from services.trpg_npc.turn_sync import collect_runtime_state_versions

            state_versions = collect_runtime_state_versions(session)
            summary["turn_sync_spawned"] = True
            summary["status"] = "ok"
            _append_observation(session, summary)
            await db.commit()

            from services.trpg_npc.turn_sync import spawn_turn_sync_task

            sync_task = spawn_turn_sync_task(
                str(session_id),
                str(user_id),
                player_text=player_text,
                gm_reply=gm_reply,
                based_on_turn_id=turn_id,
                npc_state_versions=state_versions,
                message_id=message_id,
            )
            planner_task = spawn_background_npc_planner_task(
                session_id=str(session_id),
                user_id=str(user_id),
                player_text=player_text,
                gm_reply=gm_reply,
                based_on_turn_id=turn_id,
                message_id=message_id,
            )
            # Await the grandchildren so this task only resolves after
            # the entire post-visible NPC chain has settled. The phase3
            # finaliser awaits this task's resolution.
            grandchildren = [t for t in (sync_task, planner_task) if t is not None]
            if grandchildren:
                await asyncio.gather(*grandchildren, return_exceptions=True)
            logger.info("[npc_post_visible] session=%s summary=%s", session_id, summary)
            return summary
    except Exception as exc:  # pragma: no cover - background best effort
        logger.warning(
            "[npc_post_visible] failed for session %s: %s",
            session_id,
            exc,
            exc_info=True,
        )
        summary["status"] = "error"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        if message_id:
            try:
                await record_step_standalone(
                    message_id, "post_visible_error",
                    detail=f"{type(exc).__name__}: {exc}"[:240],
                )
            except Exception:
                pass
        return summary


def _plan_routine_events(session: GameSession) -> list[Any]:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    module_state = session.module_state if isinstance(session.module_state, dict) else {}
    npcs = mem.get("npcs") if isinstance(mem.get("npcs"), list) else []
    scene_id = str(
        module_state.get("scene")
        or mem.get("current_scene")
        or "scene_unknown"
    )
    return RoutinePlanner().plan_after_visible_reply(
        active_npcs=npcs,
        scene_id=scene_id,
        in_game_period=str(module_state.get("in_game_period") or ""),
    )


def _append_observation(session: GameSession, summary: dict[str, Any]) -> None:
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    items = mem.get("_npc_post_visible_work_v2")
    if not isinstance(items, list):
        items = []
    compact = {
        "mode": summary.get("mode"),
        "turn_id": summary.get("turn_id"),
        "status": summary.get("status"),
        "warm": summary.get("warm"),
        "table_authority": summary.get("table_authority"),
        "routine_event_count": len(summary.get("routine_events") or []),
        "background_planner_spawned": bool(summary.get("background_planner_spawned")),
        "turn_sync_spawned": bool(summary.get("turn_sync_spawned")),
        "error": summary.get("error"),
    }
    items.append(compact)
    mem["_npc_post_visible_work_v2"] = items[-12:]
    session.memory_state = mem
    try:
        flag_modified(session, "memory_state")
    except Exception:
        pass
