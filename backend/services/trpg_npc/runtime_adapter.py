"""Adapter from chatrpg's session JSON NPCs to the NPC Runtime V2 contracts."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_npc.models import (
    GameEvent,
    MemoryRecord,
    NPCProfile,
    NPCState,
    RelationshipVector,
    SceneState,
)
from services.trpg_npc.optimization.safe_projection import (
    prompt_safe_active_npcs_hardened,
    scan_prompt_safety_violations,
)
from services.trpg_npc.orchestrator import NPCTurnOrchestrator, PostTurnResult
from services.trpg_npc.runtime_adapter_memory import _append_memories_v2, _write_relationships_v2
from services.trpg_npc.runtime_adapter_npc import _adapt_npc, _npc_id
from services.trpg_npc.runtime_adapter_results import (
    NPCActionBoardWarmResult,
    NPCPreTurnRuntimeResult,
)
from services.trpg_npc.runtime_adapter_session import (
    _ACTION_BOARD_KEY,
    _active_npcs_for_current_scene,
    _active_npcs_from_session,
    _attach_classified_event_metadata,
    _classified_pre_turn_events,
    _current_scene_key,
    _detect_target_ids,
    _load_action_board,
    _save_action_board,
    _scene_plot_contract,
    _session_turn_hint,
)
from services.trpg_npc.utils import new_id


logger = logging.getLogger("chatrpg.trpg_npc.runtime_adapter")


__all__ = [
    "NPCPreTurnRuntimeResult",
    "NPCActionBoardWarmResult",
    "build_npc_pre_turn_runtime",
    "warm_npc_action_board_after_turn",
    "prompt_safe_active_npcs",
    "apply_post_turn_result_to_memory_state",
    # Underscore-prefixed helpers re-exported for existing callers.
    "_adapt_npc",
    "_current_scene_key",
    "_session_turn_hint",
    "_scene_plot_contract",
    "_classified_pre_turn_events",
    "_attach_classified_event_metadata",
    "_detect_target_ids",
    "_ACTION_BOARD_KEY",
]


def build_npc_pre_turn_runtime(
    session: GameSession,
    *,
    player_text: str,
    active_npcs: list[dict[str, Any]] | None = None,
    turn_id: int | None = None,
    actor_id: str = "pc",
) -> NPCPreTurnRuntimeResult:
    """Run foreground NPC Runtime V2 over the current session, best-effort.

    This function is intentionally pure relative to the database: it does not
    mutate session.memory_state. It creates a per-turn deterministic beat plan
    from the current active NPC roster so the main GM prompt can consume a small
    adjudicated plan instead of raw NPC intent.
    """

    result = NPCPreTurnRuntimeResult()
    try:
        raw_active = active_npcs if active_npcs is not None else _active_npcs_from_session(session)
        scene_id = _current_scene_key(session) or "scene_unknown"
        resolved_turn_id = int(turn_id or _session_turn_hint(session) or 1)

        profiles: dict[str, NPCProfile] = {}
        states: dict[str, NPCState] = {}
        relationships: dict[str, dict[str, RelationshipVector]] = {}
        for npc in raw_active:
            if not isinstance(npc, dict):
                continue
            profile, state, rel = _adapt_npc(npc, scene_id=scene_id)
            profiles[profile.npc_id] = profile
            states[state.npc_id] = state
            relationships[profile.npc_id] = {actor_id: rel}

        if not profiles:
            return result

        target_ids = _detect_target_ids(player_text, raw_active, list(profiles))
        result.target_ids = target_ids
        contract = _scene_plot_contract(session, scene_id, profiles)
        scene_state = SceneState(
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            location_id=scene_id,
            active_npc_ids=list(profiles),
            plot_contract=contract,
        )
        player_event = GameEvent.player_input(
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            actor_id=actor_id,
            content=player_text or "",
            target_ids=target_ids,
        )
        classified_events = _classified_pre_turn_events(
            player_text,
            raw_active,
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            actor_id=actor_id,
        )
        recent_events = [player_event] + classified_events
        runtime = NPCTurnOrchestrator(
            action_board=_load_action_board(session),
            max_hot_npcs=1,
        )
        pre = runtime.pre_turn(
            scene_state=scene_state,
            player_event=player_event,
            profiles_by_id=profiles,
            states_by_id=states,
            relationships_by_npc=relationships,
            recent_events=recent_events,
            active_npcs=raw_active,
        )
        _attach_classified_event_metadata(pre, classified_events)
        result.pre_turn = pre
        result.scene_state = scene_state
        result.profiles_by_id = profiles
        result.states_by_id = states
        result.relationships_by_npc = relationships
        return result
    except Exception as exc:  # pragma: no cover - defensive IC prompt fallback
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def warm_npc_action_board_after_turn(
    session: GameSession,
    *,
    player_text: str,
    gm_reply: str,
    turn_id: int | None = None,
    active_npcs: list[dict[str, Any]] | None = None,
    structured_events: list[GameEvent] | None = None,
    actor_id: str = "pc",
    write_json_snapshot: bool = True,
) -> NPCActionBoardWarmResult:
    """Use the just-finished turn to persist next-turn NPC intent cards.

    This is deterministic and synchronous; it does not call an LLM. It stores
    the serialized board in `memory_state[_npc_action_board_v2]` by default so
    future pre-turn calls can match warmed cards before doing any foreground
    fallback. Phase 6 table-authority callers can disable JSON writes and
    persist the returned `post_turn` / `action_board` through Runtime tables.
    """

    result = NPCActionBoardWarmResult()
    try:
        scene_id = _current_scene_key(session) or "scene_unknown"
        result.scene_id = scene_id
        raw_active = active_npcs if active_npcs is not None else _active_npcs_for_current_scene(session)
        result.active_npc_count = len(raw_active)
        if not raw_active:
            result.skipped_reason = "no_active_npcs"
            return result

        resolved_turn_id = int(turn_id or _session_turn_hint(session) or 1)
        result.turn_id = resolved_turn_id
        profiles: dict[str, NPCProfile] = {}
        states: dict[str, NPCState] = {}
        relationships: dict[str, dict[str, RelationshipVector]] = {}
        for npc in raw_active:
            if not isinstance(npc, dict):
                continue
            profile, state, rel = _adapt_npc(npc, scene_id=scene_id)
            profiles[profile.npc_id] = profile
            states[state.npc_id] = state
            relationships[profile.npc_id] = {actor_id: rel}
        if not profiles:
            result.skipped_reason = "no_adapted_npcs"
            return result

        target_ids = _detect_target_ids(player_text, raw_active, list(profiles))
        scene_state = SceneState(
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            location_id=scene_id,
            active_npc_ids=list(profiles),
            plot_contract=_scene_plot_contract(session, scene_id, profiles),
        )
        player_event = GameEvent.player_input(
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            actor_id=actor_id,
            content=player_text or "",
            target_ids=target_ids,
        )
        if structured_events:
            committed_events = [player_event] + [
                event for event in structured_events
                if event.type != "PLAYER_INPUT"
            ]
        else:
            committed_events = [
                player_event,
                GameEvent(
                    event_id=new_id("event"),
                    type="GM_NARRATION",
                    scene_id=scene_id,
                    turn_id=resolved_turn_id,
                    actor_id="gm",
                    target_ids=target_ids,
                    content=(gm_reply or "")[:1200],
                ),
            ]
        result.committed_events = committed_events
        result.profiles_by_id = dict(profiles)
        board = _load_action_board(session)
        runtime = NPCTurnOrchestrator(action_board=board, max_hot_npcs=1)
        post = runtime.post_turn(
            scene_state=scene_state,
            committed_events=committed_events,
            profiles_by_id=profiles,
            states_by_id=states,
            relationships_by_npc=relationships,
            plan_for_next_turn=True,
        )
        runtime.action_board.expire_old(scene_id, resolved_turn_id)
        result.post_turn = post
        result.action_board = runtime.action_board
        result.planned_card_ids = list(post.planned_card_ids)
        result.stored_card_count = len(runtime.action_board.list_cards(scene_id))
        if write_json_snapshot:
            result.runtime_writeback = apply_post_turn_result_to_memory_state(session, post)
            _save_action_board(session, runtime.action_board)
        else:
            result.runtime_writeback = {
                "mode": "table_authority_pending_snapshot",
                "states": len(post.updated_states),
                "relationships": sum(
                    len(items) for items in post.updated_relationships.values()
                ),
                "memories": len(post.new_memories),
            }
        return result
    except Exception as exc:  # pragma: no cover - defensive turn fallback
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def prompt_safe_active_npcs(npcs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project NPC records into a prompt-safe shape for the main GM LLM."""

    safe = prompt_safe_active_npcs_hardened(npcs or [])
    violations = scan_prompt_safety_violations(safe)
    if violations:
        logger.warning(
            "[npc_runtime_v2] prompt-safe projection still contains suspicious fields: %s",
            violations[:8],
        )
    return safe


def apply_post_turn_result_to_memory_state(
    session: GameSession,
    post_turn: PostTurnResult,
    *,
    memory_cap: int = 20,
) -> dict[str, Any]:
    """Persist V2 post-turn state back onto `memory_state.npcs[]`.

    This keeps Phase 4 deliberately local: the current JSON session shape stays
    the storage boundary, while each NPC receives V2 subdocuments that future
    adapter reads can trust as the state authority.
    """

    summary: dict[str, Any] = {
        "states": 0,
        "relationships": 0,
        "memories": 0,
        "missing_npcs": 0,
        "capped_memories": 0,
    }
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list) or not npcs:
        summary["skipped_reason"] = "no_npcs"
        return summary

    by_id: dict[str, dict[str, Any]] = {}
    for npc in npcs:
        if isinstance(npc, dict):
            by_id[_npc_id(npc)] = npc

    memories_by_npc: dict[str, list[MemoryRecord]] = {}
    for memory in post_turn.new_memories:
        memories_by_npc.setdefault(memory.npc_id, []).append(memory)

    changed = False
    touched_ids = (
        set(post_turn.updated_states)
        | set(post_turn.updated_relationships)
        | set(memories_by_npc)
    )
    for npc_id in touched_ids:
        npc = by_id.get(npc_id)
        if npc is None:
            summary["missing_npcs"] += 1
            continue

        state = post_turn.updated_states.get(npc_id)
        if state is not None:
            npc["runtime_state_v2"] = state.to_dict()
            summary["states"] += 1
            changed = True

        relationship_count = _write_relationships_v2(
            npc,
            npc_id=npc_id,
            relationships=post_turn.updated_relationships.get(npc_id) or {},
        )
        if relationship_count:
            summary["relationships"] += relationship_count
            changed = True

        added, capped = _append_memories_v2(
            npc,
            memories_by_npc.get(npc_id) or [],
            memory_cap=memory_cap,
        )
        if added or capped:
            summary["memories"] += added
            summary["capped_memories"] += capped
            changed = True

    if changed:
        mem["npcs"] = npcs
        session.memory_state = mem
        try:
            flag_modified(session, "memory_state")
        except Exception:
            pass
    return summary
