"""Diagnostics for Runtime V2 table authority and JSON snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_ACTION_BOARD_KEY = "_npc_action_board_v2"


@dataclass(slots=True)
class NPCRuntimeSnapshotDiagnostics:
    session_id: str
    table_counts: dict[str, int]
    json_counts: dict[str, int]
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "ok": self.ok,
            "table_counts": dict(self.table_counts),
            "json_counts": dict(self.json_counts),
            "mismatches": list(self.mismatches),
            "warnings": list(self.warnings),
        }


def compare_npc_runtime_v2_snapshot(
    session: Any,
    *,
    profiles: list[Any],
    states: list[Any],
    relationships: list[Any],
    memories: list[Any],
    action_cards: list[Any],
    events: list[Any] | None = None,
    memory_cap: int = 20,
) -> NPCRuntimeSnapshotDiagnostics:
    """Compare normalized Runtime V2 rows with the compatibility JSON snapshot."""

    mem = _dict(getattr(session, "memory_state", None))
    json_npcs = _json_npcs_by_id(mem)
    json_runtime = _collect_json_runtime(mem, json_npcs)
    table_runtime = _collect_table_runtime(
        profiles=profiles,
        states=states,
        relationships=relationships,
        memories=memories,
        action_cards=action_cards,
    )
    result = NPCRuntimeSnapshotDiagnostics(
        session_id=str(getattr(session, "id", "") or ""),
        table_counts={
            "profiles": len(profiles),
            "states": len(states),
            "relationships": len(relationships),
            "memories": len(memories),
            "action_cards": len(action_cards),
            "events": len(events or []),
        },
        json_counts={
            "npcs": len(json_npcs),
            "states": len(json_runtime["states"]),
            "relationships": len(json_runtime["relationships"]),
            "memories": sum(len(items) for items in json_runtime["memories"].values()),
            "action_cards": len(json_runtime["action_cards"]),
        },
    )

    _compare_profiles(result, json_npcs, table_runtime["profiles"])
    _compare_states(result, json_npcs, json_runtime["states"], table_runtime["states"])
    _compare_relationships(
        result,
        json_npcs,
        json_runtime["relationships"],
        table_runtime["relationships"],
    )
    _compare_memories(
        result,
        json_npcs,
        json_runtime["memories"],
        table_runtime["memories"],
        memory_cap=memory_cap,
    )
    _compare_action_cards(
        result,
        json_runtime["action_cards"],
        table_runtime["action_cards"],
    )
    return result


def _compare_profiles(
    result: NPCRuntimeSnapshotDiagnostics,
    json_npcs: dict[str, dict[str, Any]],
    table_profiles: set[str],
) -> None:
    for npc_id in sorted(json_npcs):
        if table_profiles and npc_id not in table_profiles:
            result.warnings.append({
                "kind": "json_npc_missing_profile_row",
                "npc_id": npc_id,
            })
    for npc_id in sorted(table_profiles - set(json_npcs)):
        result.warnings.append({
            "kind": "table_profile_missing_json_npc",
            "npc_id": npc_id,
        })


def _compare_states(
    result: NPCRuntimeSnapshotDiagnostics,
    json_npcs: dict[str, dict[str, Any]],
    json_states: dict[str, dict[str, Any]],
    table_states: dict[str, dict[str, Any]],
) -> None:
    for npc_id, json_state in sorted(json_states.items()):
        table_state = table_states.get(npc_id)
        if not table_state:
            result.mismatches.append({
                "kind": "json_state_missing_table_row",
                "npc_id": npc_id,
                "json_state_version": _int(json_state.get("state_version")),
            })
            continue
        json_version = _int(json_state.get("state_version"))
        table_version = _int(table_state.get("state_version"))
        if json_version != table_version:
            result.mismatches.append({
                "kind": "state_version_mismatch",
                "npc_id": npc_id,
                "json_state_version": json_version,
                "table_state_version": table_version,
            })
        if json_state != table_state:
            result.warnings.append({
                "kind": "state_json_differs_from_table_row",
                "npc_id": npc_id,
            })

    for npc_id, table_state in sorted(table_states.items()):
        if npc_id in json_npcs and npc_id not in json_states:
            result.warnings.append({
                "kind": "table_state_missing_json_snapshot",
                "npc_id": npc_id,
                "table_state_version": _int(table_state.get("state_version")),
            })


def _compare_relationships(
    result: NPCRuntimeSnapshotDiagnostics,
    json_npcs: dict[str, dict[str, Any]],
    json_relationships: dict[tuple[str, str], dict[str, Any]],
    table_relationships: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for key in sorted(json_relationships):
        if key not in table_relationships:
            npc_id, target_id = key
            result.mismatches.append({
                "kind": "json_relationship_missing_table_row",
                "npc_id": npc_id,
                "target_id": target_id,
            })
            continue
        if json_relationships[key] != table_relationships[key]:
            npc_id, target_id = key
            result.warnings.append({
                "kind": "relationship_json_differs_from_table_row",
                "npc_id": npc_id,
                "target_id": target_id,
            })

    for npc_id, target_id in sorted(table_relationships):
        if npc_id in json_npcs and (npc_id, target_id) not in json_relationships:
            result.warnings.append({
                "kind": "table_relationship_missing_json_snapshot",
                "npc_id": npc_id,
                "target_id": target_id,
            })


def _compare_memories(
    result: NPCRuntimeSnapshotDiagnostics,
    json_npcs: dict[str, dict[str, Any]],
    json_memories: dict[str, list[str]],
    table_memories: dict[str, list[str]],
    *,
    memory_cap: int,
) -> None:
    cap = max(1, int(memory_cap or 20))
    for npc_id, json_ids in sorted(json_memories.items()):
        table_ids = set(table_memories.get(npc_id, []))
        for memory_id in json_ids:
            if memory_id not in table_ids:
                result.mismatches.append({
                    "kind": "json_memory_missing_table_row",
                    "npc_id": npc_id,
                    "memory_id": memory_id,
                })

    for npc_id, table_ids in sorted(table_memories.items()):
        if npc_id not in json_npcs:
            continue
        expected_latest = set(table_ids[-cap:])
        json_ids = set(json_memories.get(npc_id, []))
        missing_latest = sorted(expected_latest - json_ids)
        if missing_latest:
            result.warnings.append({
                "kind": "latest_table_memories_missing_json_snapshot",
                "npc_id": npc_id,
                "memory_ids": missing_latest,
            })


def _compare_action_cards(
    result: NPCRuntimeSnapshotDiagnostics,
    json_cards: dict[tuple[str, str], dict[str, Any]],
    table_cards: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for scene_id, card_id in sorted(json_cards):
        if (scene_id, card_id) not in table_cards:
            result.mismatches.append({
                "kind": "json_action_card_missing_table_row",
                "scene_id": scene_id,
                "card_id": card_id,
            })
            continue
        if json_cards[(scene_id, card_id)] != table_cards[(scene_id, card_id)]:
            result.warnings.append({
                "kind": "action_card_json_differs_from_table_row",
                "scene_id": scene_id,
                "card_id": card_id,
            })

    for scene_id, card_id in sorted(table_cards):
        if (scene_id, card_id) not in json_cards:
            result.warnings.append({
                "kind": "table_action_card_missing_json_snapshot",
                "scene_id": scene_id,
                "card_id": card_id,
            })


def _collect_json_runtime(
    mem: dict[str, Any],
    json_npcs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = {}
    relationships: dict[tuple[str, str], dict[str, Any]] = {}
    memories: dict[str, list[str]] = {}
    for npc_id, npc in json_npcs.items():
        state = _dict(npc.get("runtime_state_v2"))
        if state:
            states[npc_id] = state
        rels = _dict(npc.get("relationships_v2"))
        for target_id, rel in rels.items():
            rel_json = _dict(rel)
            if target_id and rel_json:
                relationships[(npc_id, str(target_id))] = rel_json
        memory_ids: list[str] = []
        raw_memories = npc.get("memories_v2")
        if isinstance(raw_memories, list):
            for item in raw_memories:
                memory_id = str(_dict(item).get("memory_id") or "").strip()
                if memory_id:
                    memory_ids.append(memory_id)
        if memory_ids:
            memories[npc_id] = memory_ids

    action_cards: dict[tuple[str, str], dict[str, Any]] = {}
    board = _dict(mem.get(_ACTION_BOARD_KEY))
    scenes = _dict(board.get("scenes"))
    for scene_id, cards in scenes.items():
        if not isinstance(cards, list):
            continue
        for card in cards:
            card_json = _dict(card)
            card_id = str(card_json.get("card_id") or "").strip()
            if card_id:
                action_cards[(str(scene_id), card_id)] = card_json

    return {
        "states": states,
        "relationships": relationships,
        "memories": memories,
        "action_cards": action_cards,
    }


def _collect_table_runtime(
    *,
    profiles: list[Any],
    states: list[Any],
    relationships: list[Any],
    memories: list[Any],
    action_cards: list[Any],
) -> dict[str, Any]:
    table_states: dict[str, dict[str, Any]] = {}
    for row in states:
        npc_id = str(_row_value(row, "npc_id") or "").strip()
        state_json = _row_json(row, "state_json")
        if npc_id and state_json:
            table_states[npc_id] = state_json

    table_relationships: dict[tuple[str, str], dict[str, Any]] = {}
    for row in relationships:
        npc_id = str(_row_value(row, "npc_id") or "").strip()
        target_id = str(_row_value(row, "target_id") or "").strip()
        rel_json = _row_json(row, "relationship_json")
        if npc_id and target_id and rel_json:
            table_relationships[(npc_id, target_id)] = rel_json

    table_memories: dict[str, list[str]] = {}
    for row in memories:
        npc_id = str(_row_value(row, "npc_id") or "").strip()
        memory_id = str(_row_value(row, "memory_id") or "").strip()
        if npc_id and memory_id:
            table_memories.setdefault(npc_id, []).append(memory_id)

    table_action_cards: dict[tuple[str, str], dict[str, Any]] = {}
    for row in action_cards:
        scene_id = str(_row_value(row, "scene_id") or "").strip()
        card_json = _row_json(row, "card_json")
        card_id = str(card_json.get("card_id") or _row_value(row, "card_id") or "").strip()
        if scene_id and card_id and card_json:
            table_action_cards[(scene_id, card_id)] = card_json

    return {
        "profiles": {
            str(_row_value(row, "npc_id") or "").strip()
            for row in profiles
            if str(_row_value(row, "npc_id") or "").strip()
        },
        "states": table_states,
        "relationships": table_relationships,
        "memories": table_memories,
        "action_cards": table_action_cards,
    }


def _json_npcs_by_id(mem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return out
    for npc in npcs:
        npc_json = _dict(npc)
        npc_id = str(npc_json.get("key") or npc_json.get("name") or "").strip()
        if npc_id:
            out[npc_id] = npc_json
    return out


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _row_json(row: Any, key: str) -> dict[str, Any]:
    return _dict(_row_value(row, key))


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
