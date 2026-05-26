"""Session-shape glue for the NPC runtime adapter (scene/action board/events)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_npc.action_board import ActionBoard
from services.trpg_npc.models import (
    GameEvent,
    NPCProfile,
    ScenePlotContract,
)
from services.trpg_npc.optimization.event_classifier import classify_player_text_to_events
from services.trpg_npc.orchestrator import PreTurnResult
from services.trpg_npc.runtime_adapter_coerce import _int, _list_strings
from services.trpg_npc.runtime_adapter_npc import _npc_id
from services.trpg_npc.utils import new_id


_ACTION_BOARD_KEY = "_npc_action_board_v2"


def _active_npcs_from_session(session: GameSession) -> list[dict[str, Any]]:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    return [n for n in npcs if isinstance(n, dict)] if isinstance(npcs, list) else []


def _active_npcs_for_current_scene(session: GameSession) -> list[dict[str, Any]]:
    npcs = _active_npcs_from_session(session)
    scene_id = _current_scene_key(session)
    if not scene_id:
        return npcs
    tagged: list[dict[str, Any]] = []
    untagged: list[dict[str, Any]] = []
    for npc in npcs:
        last_seen = str(npc.get("last_seen_scene") or "").strip()
        if last_seen:
            if last_seen == scene_id:
                tagged.append(npc)
        else:
            untagged.append(npc)
    return tagged if tagged else untagged


def _load_action_board(session: GameSession) -> ActionBoard:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    return ActionBoard.from_dict(mem.get(_ACTION_BOARD_KEY))


def _save_action_board(session: GameSession, board: ActionBoard) -> None:
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    mem[_ACTION_BOARD_KEY] = board.to_dict()
    session.memory_state = mem
    try:
        flag_modified(session, "memory_state")
    except Exception:
        pass


def _current_scene_key(session: GameSession) -> str:
    module_state = session.module_state if isinstance(session.module_state, dict) else {}
    scene = str(module_state.get("scene") or "").strip()
    if scene and scene != "—":
        return scene
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    current = str(mem.get("current_scene") or "").strip()
    if current:
        return current
    facts = mem.get("world_facts")
    if isinstance(facts, dict):
        return str(facts.get("current_scene") or "").strip()
    return ""


def _session_turn_hint(session: GameSession) -> int:
    # Good enough for a per-turn foreground budget. A persisted monotonic turn
    # id can replace this when ActionBoard storage moves out of memory_state.
    summarized = int(getattr(session, "last_summarized_msg_count", 0) or 0)
    return max(1, summarized + 1)


def _scene_plot_contract(
    session: GameSession,
    scene_id: str,
    profiles: dict[str, NPCProfile],
) -> ScenePlotContract:
    module_state = session.module_state if isinstance(session.module_state, dict) else {}
    forbidden: list[str] = []
    for profile in profiles.values():
        forbidden.extend(profile.plot_constraints.forbidden_fact_ids)
        forbidden.extend(profile.plot_constraints.core_secret_ids)
    objective = str(module_state.get("objective") or module_state.get("scene_objective") or "")
    return ScenePlotContract(
        scene_id=scene_id,
        scene_goal=objective,
        forbidden_reveals=list(dict.fromkeys(forbidden)),
        max_clue_reveals_per_turn=1,
        notes="NPC actions must stay inside the active scene and respect hidden-fact gates.",
    )


def _classified_pre_turn_events(
    player_text: str,
    active_npcs: list[dict[str, Any]],
    *,
    scene_id: str,
    turn_id: int,
    actor_id: str,
) -> list[GameEvent]:
    events: list[GameEvent] = []
    for raw in classify_player_text_to_events(
        player_text or "",
        active_npcs,
        scene_id=scene_id,
        turn_id=turn_id,
        actor_id=actor_id,
    ):
        if not isinstance(raw, dict):
            continue
        event_type = str(raw.get("type") or "").strip()
        if not event_type or event_type == "PLAYER_INPUT":
            continue
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        visibility = raw.get("visibility") if isinstance(raw.get("visibility"), dict) else {
            "player_visible": True,
            "gm_visible": True,
        }
        events.append(
            GameEvent(
                event_id=str(raw.get("event_id") or new_id("event")),
                type=event_type,
                scene_id=str(raw.get("scene_id") or scene_id),
                turn_id=_int(raw.get("turn_id"), turn_id),
                actor_id=str(raw.get("actor_id") or actor_id),
                target_ids=_list_strings(raw.get("target_ids")),
                content=str(raw.get("content") or "")[:1200],
                payload=dict(payload),
                visibility=dict(visibility),
            )
        )
    return events


def _attach_classified_event_metadata(pre: PreTurnResult | None, events: list[GameEvent]) -> None:
    if not pre or not events:
        return
    pre.beat_plan.metadata["classified_player_events"] = [
        {
            "type": event.type,
            "target_ids": list(event.target_ids),
            "confidence": event.payload.get("confidence"),
            "topic_tags": list(event.payload.get("topic_tags") or []),
        }
        for event in events
    ]


def _detect_target_ids(
    player_text: str,
    npcs: list[dict[str, Any]],
    fallback_ids: list[str],
) -> list[str]:
    text = (player_text or "").lower()
    targets: list[str] = []
    for npc in npcs:
        npc_id = _npc_id(npc)
        aliases = [
            str(npc.get("key") or ""),
            str(npc.get("player_known_name") or ""),
            str(npc.get("name") or "") if npc.get("name_revealed") else "",
        ]
        for alias in aliases:
            alias = alias.strip()
            if alias and alias.lower() in text:
                targets.append(npc_id)
                break
    if not targets and len(fallback_ids) == 1 and _has_single_npc_pronoun(text):
        targets.append(fallback_ids[0])
    return list(dict.fromkeys(targets))


def _has_single_npc_pronoun(text: str) -> bool:
    return any(token in text for token in ("他", "她", "ta", "him", "her", "them"))
