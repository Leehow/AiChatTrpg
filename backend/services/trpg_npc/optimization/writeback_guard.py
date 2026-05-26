"""Version and freshness guards for NPC Runtime V2 background writeback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .common import get_value, set_value, stable_list, to_plain_data


@dataclass(frozen=True, slots=True)
class RuntimeWritebackPolicy:
    """Controls when async NPC runtime updates may modify current state."""

    max_background_lag_turns: int = 2
    allow_equal_state_version: bool = True
    create_missing_npcs: bool = True
    reject_scene_mismatch: bool = True
    reject_future_cards: bool = True
    max_action_card_ttl_turns: int = 4


@dataclass(slots=True)
class RejectedWrite:
    kind: str
    identifier: str
    reason: str
    payload: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "reason": self.reason,
            "payload": to_plain_data(self.payload),
        }


@dataclass(slots=True)
class GuardedWritebackResult:
    applied: dict[str, int] = field(default_factory=lambda: {
        "states": 0,
        "relationships": 0,
        "memories": 0,
        "action_cards": 0,
    })
    rejected: list[RejectedWrite] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": dict(self.applied),
            "rejected": [item.to_dict() for item in self.rejected],
            "warnings": list(self.warnings),
        }


def _memory_state(session: Any) -> dict[str, Any]:
    memory_state = get_value(session, "memory_state")
    if memory_state is None:
        memory_state = {}
        set_value(session, "memory_state", memory_state)
    return memory_state


def _npcs(session: Any) -> list[dict[str, Any]]:
    memory_state = _memory_state(session)
    npcs = memory_state.setdefault("npcs", [])
    if not isinstance(npcs, list):
        return []
    clean = [npc for npc in npcs if isinstance(npc, dict)]
    if len(clean) != len(npcs):
        memory_state["npcs"] = clean
    return clean


def _npc_id_from_row(row: Any) -> str:
    return str(
        get_value(row, "npc_id")
        or get_value(get_value(row, "state_json", {}), "npc_id")
        or get_value(get_value(row, "relationship_json", {}), "npc_id")
        or get_value(get_value(row, "memory_json", {}), "npc_id")
        or "unknown_npc"
    )


def _state_json(row: Any) -> dict[str, Any]:
    value = get_value(row, "state_json") or row
    plain = to_plain_data(value)
    return plain if isinstance(plain, dict) else {}


def _relationship_json(row: Any) -> dict[str, Any]:
    value = get_value(row, "relationship_json") or row
    plain = to_plain_data(value)
    return plain if isinstance(plain, dict) else {}


def _memory_json(row: Any) -> dict[str, Any]:
    value = get_value(row, "memory_json") or row
    plain = to_plain_data(value)
    return plain if isinstance(plain, dict) else {}


def _card_json(row: Any) -> dict[str, Any]:
    value = get_value(row, "card_json") or row
    plain = to_plain_data(value)
    return plain if isinstance(plain, dict) else {}


def _find_or_create_npc(session: Any, npc_id: str, *, create_missing: bool = True) -> dict[str, Any] | None:
    for npc in _npcs(session):
        if not isinstance(npc, dict):
            continue
        if str(npc.get("key") or npc.get("npc_id") or npc.get("id")) == npc_id:
            return npc
    if not create_missing:
        return None
    npc = {"key": npc_id, "npc_id": npc_id, "name_revealed": False}
    _npcs(session).append(npc)
    return npc


def _current_state_version(npc: dict[str, Any]) -> int:
    state = npc.get("runtime_state_v2") or {}
    try:
        return int(state.get("state_version", 0))
    except (TypeError, ValueError):
        return 0


def _incoming_state_version(state: dict[str, Any]) -> int:
    try:
        return int(state.get("state_version", 0))
    except (TypeError, ValueError):
        return 0


def _is_stale_turn(based_on_turn_id: int | None, current_turn: int, policy: RuntimeWritebackPolicy) -> bool:
    if based_on_turn_id is None:
        return False
    return based_on_turn_id < current_turn - policy.max_background_lag_turns


def _extract_turn_id(row: Any) -> int | None:
    for candidate in [
        get_value(row, "based_on_turn_id"),
        get_value(row, "turn_id"),
        get_value(get_value(row, "state_json", {}), "based_on_turn_id"),
        get_value(get_value(row, "card_json", {}), "based_on_turn_id"),
    ]:
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _extract_scene_id(row: Any) -> str | None:
    for candidate in [
        get_value(row, "scene_id"),
        get_value(get_value(row, "state_json", {}), "scene_id"),
        get_value(get_value(row, "card_json", {}), "scene_id"),
    ]:
        if candidate:
            return str(candidate)
    return None


def apply_runtime_snapshot_guarded(
    session: Any,
    *,
    states: Iterable[Any] | None = None,
    relationships: Iterable[Any] | None = None,
    memories: Iterable[Any] | None = None,
    action_cards: Iterable[Any] | None = None,
    current_turn: int,
    current_scene_id: str | None,
    policy: RuntimeWritebackPolicy | None = None,
) -> GuardedWritebackResult:
    """Apply runtime rows to ``session.memory_state`` with stale-write protection.

    This function is a guarded replacement for direct JSON snapshot writes during
    the table-authority migration.  It should be called only after DB upsert has
    succeeded, or in local/lightweight mode when tables are unavailable.
    """

    policy = policy or RuntimeWritebackPolicy()
    result = GuardedWritebackResult()
    memory_state = _memory_state(session)

    for row in states or []:
        npc_id = _npc_id_from_row(row)
        state = _state_json(row)
        based_on_turn = _extract_turn_id(row)
        if _is_stale_turn(based_on_turn, current_turn, policy):
            result.rejected.append(RejectedWrite("state", npc_id, "stale_turn", row))
            continue
        scene_id = _extract_scene_id(row)
        if policy.reject_scene_mismatch and scene_id and current_scene_id and scene_id != current_scene_id:
            result.rejected.append(RejectedWrite("state", npc_id, "scene_mismatch", row))
            continue
        npc = _find_or_create_npc(session, npc_id, create_missing=policy.create_missing_npcs)
        if npc is None:
            result.rejected.append(RejectedWrite("state", npc_id, "missing_npc", row))
            continue
        incoming_version = _incoming_state_version(state)
        current_version = _current_state_version(npc)
        if incoming_version < current_version:
            result.rejected.append(
                RejectedWrite("state", npc_id, f"older_state_version:{incoming_version}<{current_version}", row)
            )
            continue
        if incoming_version == current_version and not policy.allow_equal_state_version:
            result.rejected.append(
                RejectedWrite("state", npc_id, f"equal_state_version:{incoming_version}", row)
            )
            continue
        npc["runtime_state_v2"] = state
        result.applied["states"] += 1

    for row in relationships or []:
        npc_id = _npc_id_from_row(row)
        relationship = _relationship_json(row)
        target_id = str(get_value(row, "target_id") or relationship.get("target_id") or "pc")
        npc = _find_or_create_npc(session, npc_id, create_missing=policy.create_missing_npcs)
        if npc is None:
            result.rejected.append(RejectedWrite("relationship", npc_id, "missing_npc", row))
            continue
        relationships_v2 = npc.setdefault("relationships_v2", {})
        relationships_v2[target_id] = relationship
        result.applied["relationships"] += 1

    for row in memories or []:
        npc_id = _npc_id_from_row(row)
        memory = _memory_json(row)
        memory_id = str(memory.get("memory_id") or get_value(row, "memory_id") or "")
        if not memory_id:
            result.rejected.append(RejectedWrite("memory", npc_id, "missing_memory_id", row))
            continue
        npc = _find_or_create_npc(session, npc_id, create_missing=policy.create_missing_npcs)
        if npc is None:
            result.rejected.append(RejectedWrite("memory", npc_id, "missing_npc", row))
            continue
        memories_v2 = npc.setdefault("memories_v2", [])
        existing_ids = {str(item.get("memory_id")) for item in memories_v2 if isinstance(item, dict)}
        if memory_id in existing_ids:
            continue
        memories_v2.append(memory)
        result.applied["memories"] += 1

    for row in action_cards or []:
        card = _card_json(row)
        card_id = str(card.get("card_id") or get_value(row, "card_id") or "")
        if not card_id:
            result.rejected.append(RejectedWrite("action_card", "unknown", "missing_card_id", row))
            continue
        scene_id = str(card.get("scene_id") or get_value(row, "scene_id") or current_scene_id or "global")
        based_on = _extract_turn_id(row)
        if policy.reject_future_cards and based_on is not None and based_on > current_turn:
            result.rejected.append(RejectedWrite("action_card", card_id, "future_card", row))
            continue
        if _is_stale_turn(based_on, current_turn, policy):
            result.rejected.append(RejectedWrite("action_card", card_id, "stale_turn", row))
            continue
        valid_until = card.get("valid_until_turn")
        try:
            valid_until_int = int(valid_until) if valid_until is not None else current_turn + policy.max_action_card_ttl_turns
        except (TypeError, ValueError):
            valid_until_int = current_turn + policy.max_action_card_ttl_turns
        if valid_until_int < current_turn:
            result.rejected.append(RejectedWrite("action_card", card_id, "expired", row))
            continue
        if valid_until_int > current_turn + policy.max_action_card_ttl_turns:
            card["valid_until_turn"] = current_turn + policy.max_action_card_ttl_turns
            result.warnings.append(f"clamped_action_card_ttl:{card_id}")

        board = memory_state.get("_npc_action_board_v2")
        if not isinstance(board, dict):
            board = {"version": 1, "scenes": {}}
            memory_state["_npc_action_board_v2"] = board
        board.setdefault("version", 1)
        scenes = board.get("scenes")
        if not isinstance(scenes, dict):
            scenes = {}
            board["scenes"] = scenes
        scene_cards = scenes.setdefault(scene_id, [])
        existing_index = next((i for i, item in enumerate(scene_cards) if item.get("card_id") == card_id), None)
        if existing_index is None:
            scene_cards.append(card)
            result.applied["action_cards"] += 1
        else:
            existing = scene_cards[existing_index]
            existing_based_on = existing.get("based_on_turn_id")
            try:
                existing_based_on_int = int(existing_based_on) if existing_based_on is not None else -1
            except (TypeError, ValueError):
                existing_based_on_int = -1
            incoming_based_on_int = based_on if based_on is not None else -1
            if incoming_based_on_int >= existing_based_on_int:
                scene_cards[existing_index] = card
                result.applied["action_cards"] += 1
            else:
                result.rejected.append(RejectedWrite("action_card", card_id, "older_card_based_on_turn", row))

    return result
