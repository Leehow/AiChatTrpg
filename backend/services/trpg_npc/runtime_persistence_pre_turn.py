"""Pure table-row pre-turn builder for NPC Runtime V2.

Splitting this off keeps the public `runtime_persistence` facade under the
600-line policy.  The function is re-exported from `runtime_persistence` so
existing imports continue to resolve.
"""

from __future__ import annotations

from typing import Any

from orm.models import GameSession
from services.trpg_npc.models import (
    GameEvent,
    NPCProfile,
    NPCState,
    RelationshipVector,
    SceneState,
)
from services.trpg_npc.orchestrator import NPCTurnOrchestrator
from services.trpg_npc.runtime_adapter import (
    NPCPreTurnRuntimeResult,
    _adapt_npc,
    _attach_classified_event_metadata,
    _classified_pre_turn_events,
    _current_scene_key,
    _detect_target_ids,
    _scene_plot_contract,
    _session_turn_hint,
)
from services.trpg_npc.runtime_persistence_helpers import (
    _action_board_from_rows,
    _active_npcs_from_session_json,
    _row_json,
    _row_value,
)
from services.trpg_npc.runtime_persistence_hydration import (
    _profile_from_json,
    _relationship_from_json,
    _state_from_json,
)


def build_npc_pre_turn_runtime_from_table_rows(
    session: GameSession,
    *,
    player_text: str,
    active_npcs: list[dict[str, Any]] | None = None,
    turn_id: int | None = None,
    actor_id: str = "pc",
    profile_rows: list[Any] | None = None,
    state_rows: list[Any] | None = None,
    relationship_rows: list[Any] | None = None,
    action_card_rows: list[Any] | None = None,
) -> NPCPreTurnRuntimeResult:
    """Pure table-row pre-turn builder used by async DB path and tests."""

    result = NPCPreTurnRuntimeResult()
    try:
        raw_active = active_npcs if active_npcs is not None else _active_npcs_from_session_json(session)
        scene_id = _current_scene_key(session) or "scene_unknown"
        resolved_turn_id = int(turn_id or _session_turn_hint(session) or 1)

        fallback_profiles: dict[str, NPCProfile] = {}
        fallback_states: dict[str, NPCState] = {}
        fallback_relationships: dict[str, RelationshipVector] = {}
        for npc in raw_active:
            if not isinstance(npc, dict):
                continue
            profile, state, rel = _adapt_npc(npc, scene_id=scene_id)
            fallback_profiles[profile.npc_id] = profile
            fallback_states[state.npc_id] = state
            fallback_relationships[profile.npc_id] = rel

        if not fallback_profiles:
            return result

        profiles = dict(fallback_profiles)
        profile_by_id = {
            str(_row_value(row, "npc_id") or ""): row
            for row in profile_rows or []
        }
        for npc_id, row in profile_by_id.items():
            if npc_id in fallback_profiles:
                profiles[npc_id] = _profile_from_json(
                    _row_json(row, "profile_json"),
                    fallback=fallback_profiles[npc_id],
                )

        states = dict(fallback_states)
        for row in state_rows or []:
            npc_id = str(_row_value(row, "npc_id") or "")
            if npc_id in fallback_states:
                states[npc_id] = _state_from_json(
                    _row_json(row, "state_json"),
                    fallback=fallback_states[npc_id],
                )

        relationships: dict[str, dict[str, RelationshipVector]] = {
            npc_id: {actor_id: rel}
            for npc_id, rel in fallback_relationships.items()
        }
        for row in relationship_rows or []:
            npc_id = str(_row_value(row, "npc_id") or "")
            target_id = str(_row_value(row, "target_id") or "")
            if npc_id in relationships and target_id:
                relationships.setdefault(npc_id, {})[target_id] = _relationship_from_json(
                    _row_json(row, "relationship_json"),
                    fallback=relationships.get(npc_id, {}).get(target_id, RelationshipVector()),
                )

        target_ids = _detect_target_ids(player_text, raw_active, list(profiles))
        result.target_ids = target_ids
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
        classified_events = _classified_pre_turn_events(
            player_text,
            raw_active,
            scene_id=scene_id,
            turn_id=resolved_turn_id,
            actor_id=actor_id,
        )
        recent_events = [player_event] + classified_events
        runtime = NPCTurnOrchestrator(
            action_board=_action_board_from_rows(action_card_rows or []),
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
    except Exception as exc:  # pragma: no cover - defensive table fallback
        result.error = f"{type(exc).__name__}: {exc}"
        return result
