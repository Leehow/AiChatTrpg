"""Background LLM planner for Runtime V2 ActionBoard cards.

This is Phase 7's conservative entry point: the foreground turn never waits on
the LLM. After the GM reply is saved and the table-authority Runtime V2
writeback commits, this task can ask a model for richer next-turn intent cards
for important in-scene NPCs. The ActionResolver still owns final adjudication.

The facade keeps the orchestration entry points (spawn + plan + background
runner). Card construction, prompt assembly, observation persistence, and the
shared constants/utilities live in same-prefix helper modules so each file
stays under the 600-line hard threshold.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.trpg.llm_json import call_llm_json_task
from core.database import get_session_factory
from orm.models import GameSession
from services.trpg_npc.action_board import ActionBoard
from services.trpg_npc.background_planner_cards import (
    PlannerCardBuildDiagnostics,
    PlannerCardBuildResult,
    build_cards_from_planner_response,
    build_cards_from_planner_response_detailed,
)
from services.trpg_npc.background_planner_constants import (
    _DEFAULT_TIMEOUT_SECONDS,
    _MAX_NPCS,
    _SYSTEM_PROMPT,
)
from services.trpg_npc.background_planner_observation import (
    append_background_planner_observation,
    background_planner_snapshot,
    compact_background_planner_summary,
)
from services.trpg_npc.background_planner_prompt import (
    build_background_planner_prompt,
    select_background_planner_npc_ids,
)
from services.trpg_npc.knowledge_runtime import build_npc_knowledge_runtime
from services.trpg_npc.runtime_adapter import NPCActionBoardWarmResult
from services.trpg_npc.runtime_persistence import (
    build_npc_pre_turn_runtime_from_tables,
    build_npc_runtime_v2_table_payloads,
    hydrate_npc_runtime_v2_from_tables,
    persist_npc_runtime_v2_table_payload,
)


logger = logging.getLogger("chatrpg.trpg_npc.background_planner")

_INFLIGHT: set[asyncio.Task] = set()


__all__ = [
    "PlannerCardBuildDiagnostics",
    "PlannerCardBuildResult",
    "append_background_planner_observation",
    "background_planner_snapshot",
    "build_background_planner_prompt",
    "build_cards_from_planner_response",
    "build_cards_from_planner_response_detailed",
    "compact_background_planner_summary",
    "plan_background_npc_actions",
    "select_background_planner_npc_ids",
    "spawn_background_npc_planner_task",
]


def spawn_background_npc_planner_task(
    session_id: str,
    user_id: str,
    *,
    player_text: str,
    gm_reply: str,
    based_on_turn_id: int,
    message_id: str = "",
) -> asyncio.Task:
    """Fire-and-forget background planner. The active IC turn does not wait."""

    task = asyncio.create_task(
        _run_background_planner(
            session_id=session_id,
            user_id=user_id,
            player_text=player_text,
            gm_reply=gm_reply,
            based_on_turn_id=based_on_turn_id,
            message_id=message_id,
        )
    )
    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)
    return task


async def plan_background_npc_actions(
    db: Any,
    session: GameSession,
    *,
    player_text: str,
    gm_reply: str,
    cfg: dict[str, Any],
    based_on_turn_id: int,
    max_npcs: int = _MAX_NPCS,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Plan richer next-turn ActionBoard cards for important active NPCs."""

    summary: dict[str, Any] = {
        "mode": "llm_background_action_board",
        "status": "skipped",
        "based_on_turn_id": int(based_on_turn_id or 0),
        "model": str(cfg.get("model") or ""),
        "considered": 0,
        "selected": 0,
        "selected_npc_ids": [],
        "planned": 0,
        "planned_card_ids": [],
        "persisted_action_cards": 0,
        "skipped": "",
    }
    if not (cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")):
        summary["skipped"] = "missing_llm_config"
        return summary

    from services.trpg_scene_runtime import compute_active_npcs

    active_npcs = compute_active_npcs(session)
    if not active_npcs:
        summary["skipped"] = "no_active_npcs"
        return summary

    runtime = await build_npc_pre_turn_runtime_from_tables(
        db,
        session,
        player_text=player_text,
        active_npcs=active_npcs,
        turn_id=based_on_turn_id,
    )
    profiles = runtime.profiles_by_id
    states = runtime.states_by_id
    relationships = runtime.relationships_by_npc
    selected_ids = select_background_planner_npc_ids(
        profiles,
        active_npcs=active_npcs,
        max_npcs=max_npcs,
    )
    summary["considered"] = len(profiles)
    summary["selected"] = len(selected_ids)
    summary["selected_npc_ids"] = list(selected_ids)
    if not selected_ids:
        summary["skipped"] = "no_l2_l3_active_npcs"
        return summary

    selected_profiles = {npc_id: profiles[npc_id] for npc_id in selected_ids}
    scene_id = runtime.scene_state.scene_id if runtime.scene_state else ""
    knowledge_runtime = await build_npc_knowledge_runtime(
        db,
        session,
        npc_ids=selected_ids,
        scene_id=scene_id,
    )
    summary["knowledge_profile"] = knowledge_runtime.summary()
    prompt = build_background_planner_prompt(
        profiles_by_id=selected_profiles,
        states_by_id=states,
        relationships_by_npc=relationships,
        knowledge_profiles_by_npc_id=knowledge_runtime.prompt_payloads_by_npc_id(),
        scene_id=scene_id,
        turn_id=based_on_turn_id,
        player_text=player_text,
        gm_reply=gm_reply,
    )
    try:
        raw = await asyncio.wait_for(
            call_llm_json_task(
                stage="npc_background_planner",
                model=str(cfg["model"]),
                base_url=str(cfg["base_url"]),
                api_key=str(cfg["api_key"]),
                system_prefix=_SYSTEM_PROMPT,
                user_message=prompt,
                stream=False,
            ),
            timeout=max(1.0, float(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)),
        )
    except Exception as exc:
        logger.warning("[npc_background_planner] LLM failed: %s", exc, exc_info=True)
        summary["skipped"] = f"llm_failed: {type(exc).__name__}"
        return summary

    build_result = build_cards_from_planner_response_detailed(
        raw,
        profiles_by_id=selected_profiles,
        based_on_turn_id=based_on_turn_id,
        forbidden_memories_by_npc_id=knowledge_runtime.forbidden_memories_by_npc_id,
    )
    cards = build_result.cards
    card_build = build_result.diagnostics.to_dict()
    summary["planner_card_build"] = card_build
    summary["structured_trigger_count"] = card_build["structured_trigger_count"]
    summary["legacy_trigger_count"] = card_build["legacy_trigger_count"]
    summary["secret_guard_transformed"] = card_build["secret_guard_transformed"]
    summary["secret_guard_blocked"] = card_build["secret_guard_blocked"]
    summary["knowledge_leak_warning_count"] = card_build["knowledge_leak_warning_count"]
    summary["knowledge_leak_blocked"] = card_build["knowledge_leak_blocked"]
    summary["invalid_planner_cards"] = (
        card_build["invalid_card_count"]
        + card_build["unknown_npc_count"]
        + card_build["duplicate_npc_count"]
        + card_build["knowledge_leak_blocked"]
    )
    if not cards:
        summary["skipped"] = "empty_cards"
        return summary

    scene_id = runtime.scene_state.scene_id if runtime.scene_state else "scene_unknown"
    board = ActionBoard()
    board.upsert(scene_id, cards)
    warm_result = NPCActionBoardWarmResult(
        action_board=board,
        profiles_by_id=selected_profiles,
        scene_id=scene_id,
        turn_id=based_on_turn_id,
        active_npc_count=len(active_npcs),
        planned_card_ids=[card.card_id for card in cards],
        stored_card_count=len(cards),
        runtime_writeback={"mode": "llm_background_planner"},
    )
    payload = build_npc_runtime_v2_table_payloads(session, warm_result)
    await persist_npc_runtime_v2_table_payload(db, payload)
    snapshot = await hydrate_npc_runtime_v2_from_tables(
        db,
        session,
        current_turn=based_on_turn_id,
        current_scene_id=scene_id,
    )

    summary["planned"] = len(cards)
    summary["planned_card_ids"] = [card.card_id for card in cards]
    summary["persisted_action_cards"] = len(payload.action_cards)
    summary["json_snapshot"] = snapshot
    summary["status"] = "planned"
    summary["skipped"] = ""
    return summary


async def _run_background_planner(
    *,
    session_id: str,
    user_id: str,
    player_text: str,
    gm_reply: str,
    based_on_turn_id: int,
    message_id: str = "",
) -> None:
    from services.trpg_postprocess_steps import step_timer

    factory = get_session_factory()
    async with step_timer(message_id, "intent_planner") as handle:
        try:
            async with factory() as db:
                session = await db.get(GameSession, session_id)
                if session is None or session.user_id != user_id:
                    handle["detail"] = "skipped: session missing"
                    return
                from routes.rulesets import _resolve_default_compiler_config

                cfg = await _resolve_default_compiler_config(db)
                summary = await plan_background_npc_actions(
                    db,
                    session,
                    player_text=player_text,
                    gm_reply=gm_reply,
                    cfg=cfg,
                    based_on_turn_id=based_on_turn_id,
                )
                append_background_planner_observation(session, summary)
                await db.commit()
                logger.info(
                    "[npc_background_planner] session=%s summary=%s",
                    session_id,
                    summary,
                )
                model_name = str(cfg.get("model") or "?")
                handle["detail"] = (
                    f"{model_name} | "
                    f"cards={summary.get('cards_built', 0)} "
                    f"npcs={summary.get('npc_count', 0)}"
                )
        except Exception as exc:
            logger.warning(
                "[npc_background_planner] background task crashed for session %s",
                session_id,
                exc_info=True,
            )
            handle["detail"] = f"error: {type(exc).__name__}"
