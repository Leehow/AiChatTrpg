"""Apply confirmed StateChange objects to a structured world-state snapshot."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, MutableMapping, Protocol

from .turn_output_contract import StateChange, StateChangeType, StateOperation


@dataclass(frozen=True)
class AppliedStateChange:
    change: StateChange
    previous_value: Any
    new_value: Any
    path: tuple[str, ...]


@dataclass(frozen=True)
class StateApplyResult:
    world_state: dict[str, Any]
    applied: tuple[AppliedStateChange, ...]
    errors: tuple[str, ...] = field(default_factory=tuple)


class WorldStateStore(Protocol):
    def get_snapshot(self, campaign_id: str) -> dict[str, Any]: ...
    def save_snapshot(self, campaign_id: str, world_state: dict[str, Any]) -> dict[str, Any]: ...


class InMemoryWorldStateStore:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        if initial is not None:
            self._states["default"] = deepcopy(initial)

    def get_snapshot(self, campaign_id: str) -> dict[str, Any]:
        return deepcopy(self._states.get(campaign_id, self._states.get("default", {})))

    def save_snapshot(self, campaign_id: str, world_state: dict[str, Any]) -> dict[str, Any]:
        self._states[campaign_id] = deepcopy(world_state)
        return deepcopy(world_state)


class StateChangeApplier:
    def apply_to_snapshot(self, world_state: dict[str, Any], changes: tuple[StateChange, ...]) -> StateApplyResult:
        state = deepcopy(world_state)
        applied: list[AppliedStateChange] = []
        errors: list[str] = []
        for change in changes:
            if change.requires_rule_confirmation and not change.rule_check_id:
                errors.append(f"{change.change_id}: requires rule confirmation but has no rule_check_id")
                continue
            path = change.path or self._default_path(change)
            try:
                previous = self._get_path(state, path)
                new_value = self._apply_operation(state, path, change.operation, change.value)
                applied_change = replace(change, path=path)
                applied.append(AppliedStateChange(change=applied_change, previous_value=previous, new_value=new_value, path=path))
            except Exception as exc:  # noqa: BLE001 - keep scaffold robust for integration tests
                errors.append(f"{change.change_id}: {exc}")
        return StateApplyResult(world_state=state, applied=tuple(applied), errors=tuple(errors))

    def apply_and_save(self, *, store: WorldStateStore, campaign_id: str, changes: tuple[StateChange, ...]) -> StateApplyResult:
        snapshot = store.get_snapshot(campaign_id)
        result = self.apply_to_snapshot(snapshot, changes)
        if not result.errors:
            store.save_snapshot(campaign_id, result.world_state)
        return result

    def _default_path(self, change: StateChange) -> tuple[str, ...]:
        if change.type == StateChangeType.ENTITY_LOCATION:
            return ("entities", change.target_id, "location")
        if change.type == StateChangeType.ITEM_TRANSFER:
            return ("entities", change.target_id, "owner")
        if change.type == StateChangeType.NPC_ATTITUDE:
            return ("npcs", change.target_id, "attitude")
        if change.type == StateChangeType.NPC_EMOTION:
            return ("npcs", change.target_id, "emotion")
        if change.type == StateChangeType.CHARACTER_DAMAGE:
            return ("characters", change.target_id, "hp")
        if change.type == StateChangeType.RESOURCE_CHANGE:
            return ("resources", change.target_id)
        if change.type == StateChangeType.CLUE_DISCOVERED:
            return ("clues", change.target_id, "status")
        if change.type == StateChangeType.SCENE_TRANSITION:
            return ("scene", "current")
        if change.type == StateChangeType.TIME_ADVANCE:
            return ("time", "current")
        if change.type == StateChangeType.STATUS_EFFECT:
            return ("entities", change.target_id, "status_effects")
        return ("custom", change.target_id)

    def _get_path(self, state: dict[str, Any], path: tuple[str, ...]) -> Any:
        cur: Any = state
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return deepcopy(cur)

    def _ensure_parent(self, state: MutableMapping[str, Any], path: tuple[str, ...]) -> MutableMapping[str, Any]:
        if not path:
            raise ValueError("path must not be empty")
        cur: MutableMapping[str, Any] = state
        for part in path[:-1]:
            nxt = cur.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise TypeError(f"path segment {part!r} exists but is not an object")
            cur = nxt
        return cur

    def _apply_operation(self, state: dict[str, Any], path: tuple[str, ...], operation: StateOperation, value: Any) -> Any:
        parent = self._ensure_parent(state, path)
        key = path[-1]
        if operation == StateOperation.SET:
            parent[key] = deepcopy(value)
        elif operation == StateOperation.INCREMENT:
            previous = parent.get(key, 0)
            if previous is None:
                previous = 0
            if not isinstance(previous, (int, float)) or not isinstance(value, (int, float)):
                raise TypeError("increment operation requires numeric previous and value")
            parent[key] = previous + value
        elif operation == StateOperation.APPEND_UNIQUE:
            current = parent.setdefault(key, [])
            if not isinstance(current, list):
                raise TypeError("append_unique operation requires a list target")
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item not in current:
                    current.append(item)
        elif operation == StateOperation.REMOVE:
            current = parent.get(key)
            if isinstance(current, list):
                values = value if isinstance(value, list) else [value]
                parent[key] = [item for item in current if item not in values]
            else:
                parent.pop(key, None)
        elif operation == StateOperation.MERGE:
            if not isinstance(value, dict):
                raise TypeError("merge operation requires object value")
            current = parent.setdefault(key, {})
            if not isinstance(current, dict):
                raise TypeError("merge operation target must be an object")
            current.update(deepcopy(value))
        else:
            raise ValueError(f"unsupported operation: {operation}")
        return deepcopy(parent.get(key))
