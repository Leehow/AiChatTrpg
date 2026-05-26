"""Bridge the existing live IC runner into authoritative state-change rows.

The current live runner still receives framework markers, ChatRPG extension
markers, and optional structured events. This adapter turns those artifacts into
StateChange objects and persists them as ``TRPGStateChange`` rows plus a
``TRPGWorldStateSnapshot``.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, TRPGStateChange, TRPGWorldStateSnapshot
from services.trpg_context.models import Visibility
from services.trpg_ic_markers import IcMarkerExtraction
from services.trpg_npc.models import GameEvent
from services.trpg_runtime.event_sourcing import semantic_event_view, semantic_state_changes_for_event
from services.trpg_runtime.state_change_applier import AppliedStateChange, StateChangeApplier
from services.trpg_runtime.turn_output_contract import StateChange, StateChangeType, StateOperation


def build_state_changes_for_live_turn(
    *,
    session: GameSession,
    turn_id: str,
    structured_events: Iterable[GameEvent] = (),
    parsed_markers: Iterable[dict[str, Any]] = (),
    extension: IcMarkerExtraction | None = None,
    assistant_text: str = "",
    player_message: str = "",
) -> tuple[StateChange, ...]:
    """Build deterministic StateChange objects from existing turn artifacts.

    `player_message` is the raw player input for the turn — used to
    detect `[debug]` event-test directives so we can drop state-write
    markers (UPDATE_PC_PARAMS / UPDATE_NPC_PARAMS) the GM emits from a
    debug-only event injection. Pass empty string for callers that
    don't have it (older code paths).
    """

    changes: list[StateChange] = []
    for event in structured_events:
        payload = event.to_dict() if hasattr(event, "to_dict") else dict(getattr(event, "__dict__", {}))
        view = semantic_event_view(event)
        changes.extend(semantic_state_changes_for_event(view, turn_id=turn_id))
        changes.append(StateChange(
            change_id=_change_id(turn_id, "structured", event.event_id),
            type=StateChangeType.CUSTOM,
            target_id=event.event_id,
            operation=StateOperation.APPEND_UNIQUE,
            value=payload,
            path=("turn_events", turn_id),
            actor_id=event.actor_id,
            source_turn_id=turn_id,
            visibility=view.visibility,
            confidence=1.0,
            reason=event.content[:300],
            tags=("structured_event", view.normalized_type, "audit"),
            metadata={
                "source": "structured_events",
                "source_event_id": event.event_id,
                "player_visible": view.player_visible,
            },
        ))

    for idx, marker in enumerate(parsed_markers or ()):
        if not isinstance(marker, dict):
            continue
        kind = str(marker.get("kind") or marker.get("type") or "marker").strip() or "marker"
        changes.append(StateChange(
            change_id=_change_id(turn_id, "marker", kind, str(idx)),
            type=StateChangeType.CUSTOM,
            target_id=kind,
            operation=StateOperation.APPEND_UNIQUE,
            value=_json_safe(marker),
            path=("framework_markers", turn_id),
            source_turn_id=turn_id,
            visibility=Visibility.GM_ONLY,
            confidence=0.95,
            reason=f"framework marker {kind}",
            tags=("framework_marker", kind),
            metadata={"source": "parsed_markers"},
        ))

    if extension is not None:
        changes.extend(_changes_from_extension(
            extension,
            turn_id=turn_id,
            player_message=player_message,
        ))

    if assistant_text:
        changes.append(StateChange(
            change_id=_change_id(turn_id, "narration_digest"),
            type=StateChangeType.CUSTOM,
            target_id="last_visible_narration",
            operation=StateOperation.SET,
            value={"chars": len(assistant_text), "preview": assistant_text[:280]},
            path=("turn_meta", turn_id, "visible_narration"),
            source_turn_id=turn_id,
            visibility=Visibility.GM_ONLY,
            confidence=1.0,
            reason="visible narration recorded for audit; not canonical fact",
            tags=("audit", "narration_anchor"),
        ))

    return tuple(changes)


async def persist_state_changes_for_turn(
    db: AsyncSession,
    session: GameSession,
    *,
    campaign_id: str,
    turn_id: str,
    changes: tuple[StateChange, ...],
) -> dict[str, Any]:
    """Apply state changes to a durable snapshot and write change rows.

    If any state change fails, no change id is returned as confirmed. The caller
    can still store the error in TurnTrace, but MemoryCommitGate must not use
    partial applied ids as evidence.
    """

    if not changes:
        return {"proposed": 0, "confirmed_state_change_ids": [], "errors": []}

    snapshot_row = await _get_or_create_snapshot(db, session, campaign_id=campaign_id)
    base_state = dict(snapshot_row.state_json or {})
    if not base_state:
        base_state = _world_state_from_session(session)

    applier = StateChangeApplier()
    result = applier.apply_to_snapshot(base_state, changes)
    if result.errors:
        return {
            "proposed": len(changes),
            "confirmed_state_change_ids": [],
            "errors": list(result.errors),
        }

    for applied in result.applied:
        await _upsert_change_row(db, session, campaign_id=campaign_id, turn_id=turn_id, applied=applied)

    snapshot_row.state_json = result.world_state
    snapshot_row.version = int(snapshot_row.version or 0) + 1
    await db.flush()
    return {
        "proposed": len(changes),
        "confirmed_state_change_ids": [applied.change.change_id for applied in result.applied],
        "errors": [],
        "snapshot_version": snapshot_row.version,
    }


async def _get_or_create_snapshot(
    db: AsyncSession,
    session: GameSession,
    *,
    campaign_id: str,
) -> TRPGWorldStateSnapshot:
    row = (
        await db.execute(
            select(TRPGWorldStateSnapshot).where(TRPGWorldStateSnapshot.session_id == session.id).limit(1)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = TRPGWorldStateSnapshot(
        session_id=session.id,
        campaign_id=campaign_id,
        state_json=_world_state_from_session(session),
        version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def _upsert_change_row(
    db: AsyncSession,
    session: GameSession,
    *,
    campaign_id: str,
    turn_id: str,
    applied: AppliedStateChange,
) -> TRPGStateChange:
    existing = (
        await db.execute(
            select(TRPGStateChange)
            .where(TRPGStateChange.session_id == session.id)
            .where(TRPGStateChange.change_id == applied.change.change_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    row = existing or TRPGStateChange(
        id=str(uuid.uuid4()),
        session_id=session.id,
        campaign_id=campaign_id,
        turn_id=turn_id,
        change_id=applied.change.change_id,
    )
    row.campaign_id = campaign_id
    row.turn_id = turn_id
    row.change_type = applied.change.type.value
    row.target_id = applied.change.target_id
    row.operation = applied.change.operation.value
    row.path_json = list(applied.path)
    row.value_json = _json_safe(applied.change.value)
    row.previous_value_json = _json_safe(applied.previous_value)
    row.new_value_json = _json_safe(applied.new_value)
    row.actor_id = applied.change.actor_id or ""
    row.visibility = applied.change.visibility.value
    row.confidence = float(applied.change.confidence)
    row.reason = applied.change.reason or ""
    row.requires_rule_confirmation = bool(applied.change.requires_rule_confirmation)
    row.rule_check_id = applied.change.rule_check_id or ""
    row.tags_json = list(applied.change.tags)
    if existing is None:
        db.add(row)
    return row


def _changes_from_extension(
    extension: IcMarkerExtraction,
    *,
    turn_id: str,
    player_message: str = "",
) -> list[StateChange]:
    changes: list[StateChange] = []
    minutes_added = 0
    if extension.day_ended:
        minutes_added += 8 * 60
    if extension.time_leap_days > 0:
        minutes_added += extension.time_leap_days * 24 * 60
    minutes_added += int(extension.elapsed_minutes or 0)
    if minutes_added:
        changes.append(StateChange(
            change_id=_change_id(turn_id, "time", "elapsed_minutes"),
            type=StateChangeType.TIME_ADVANCE,
            target_id="elapsed_minutes",
            operation=StateOperation.INCREMENT,
            value=minutes_added,
            path=("time", "elapsed_minutes"),
            source_turn_id=turn_id,
            visibility=Visibility.PARTY_KNOWN,
            reason="[TAKE_TIME] marker",
            tags=("extension_marker", "take_time"),
        ))
    if extension.target_clock:
        changes.append(StateChange(
            change_id=_change_id(turn_id, "time", "target_clock"),
            type=StateChangeType.TIME_ADVANCE,
            target_id="in_game_time",
            operation=StateOperation.SET,
            value=extension.target_clock,
            path=("time", "in_game_time"),
            source_turn_id=turn_id,
            visibility=Visibility.PARTY_KNOWN,
            reason="[TAKE_TIME] target clock",
            tags=("extension_marker", "take_time"),
        ))
    if extension.objective:
        changes.append(StateChange(
            change_id=_change_id(turn_id, "objective"),
            type=StateChangeType.CUSTOM,
            target_id="objective",
            operation=StateOperation.SET,
            value=extension.objective,
            path=("plot", "objective"),
            source_turn_id=turn_id,
            visibility=Visibility.PARTY_KNOWN,
            reason="[SET_OBJECTIVE] marker",
            tags=("extension_marker", "objective"),
        ))
    for idx, note in enumerate(extension.notes):
        changes.append(StateChange(
            change_id=_change_id(turn_id, "note", str(idx)),
            type=StateChangeType.CUSTOM,
            target_id=str(note.get("id") or idx),
            operation=StateOperation.APPEND_UNIQUE,
            value=_json_safe(note),
            path=("player_notes",),
            source_turn_id=turn_id,
            visibility=Visibility.PARTY_KNOWN,
            reason="[ADD_NOTE] marker",
            tags=("extension_marker", "note"),
        ))
    # Debug-mode safety: when the player message scopes a [debug]…[/debug]
    # event-test directive (no `force write` keyword), suppress PC/NPC
    # state writes so a casual SAN/HP/condition test doesn't overwrite
    # the saved character. See services/trpg_debug_tag.py.
    from services.trpg_debug_tag import should_block_debug_state_marker
    block_npc_params = should_block_debug_state_marker(
        "update_npc_params", player_message,
    )
    block_pc_params = should_block_debug_state_marker(
        "update_pc_params", player_message,
    )
    for idx, entry in enumerate(extension.npc_param_updates):
        if block_npc_params:
            continue
        npc_key = str(entry.get("npc_key") or "unknown")
        changes.append(StateChange(
            change_id=_change_id(turn_id, "npc_params", npc_key, str(idx)),
            type=StateChangeType.CUSTOM,
            target_id=npc_key,
            operation=StateOperation.MERGE,
            value=_json_safe(entry.get("updates") or {}),
            path=("npcs", npc_key, "params"),
            source_turn_id=turn_id,
            visibility=Visibility.GM_ONLY,
            reason=str(entry.get("reason") or "[UPDATE_NPC_PARAMS] marker"),
            tags=("extension_marker", "npc_params"),
        ))
    if extension.pc_param_update is not None and not block_pc_params:
        changes.append(StateChange(
            change_id=_change_id(turn_id, "pc_params"),
            type=StateChangeType.CUSTOM,
            target_id="player_character",
            operation=StateOperation.MERGE,
            value=_json_safe(extension.pc_param_update.get("updates") or {}),
            path=("characters", "player_character", "params"),
            source_turn_id=turn_id,
            visibility=Visibility.PARTY_KNOWN,
            reason=str(extension.pc_param_update.get("reason") or "[UPDATE_PC_PARAMS] marker"),
            tags=("extension_marker", "pc_params"),
        ))
    return changes


def _world_state_from_session(session: GameSession) -> dict[str, Any]:
    module_state = dict(session.module_state) if isinstance(session.module_state, dict) else {}
    memory_state = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    character = dict(session.character) if isinstance(session.character, dict) else {}
    return {
        "scene": {"current": module_state.get("scene") or memory_state.get("current_scene")},
        "time": {
            "elapsed_minutes": int(module_state.get("elapsed_minutes") or 0),
            "in_game_time": module_state.get("in_game_time"),
            "day_count": module_state.get("day_count"),
        },
        "plot": {"objective": module_state.get("objective")},
        "characters": {"player_character": deepcopy(character)},
        "legacy_memory_state": deepcopy(memory_state),
    }


def _change_id(*parts: str) -> str:
    clean = [str(p).strip().replace(" ", "_") for p in parts if str(p).strip()]
    return "chg_" + "_".join(clean)[:88]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)
