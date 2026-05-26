"""Table-authority migration utilities for NPC Runtime V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RUNTIME_TABLE_UNIQUE_KEYS: dict[str, tuple[str, ...]] = {
    "npc_profiles": ("session_id", "npc_id"),
    "npc_states": ("session_id", "npc_id"),
    "npc_relationships": ("session_id", "npc_id", "target_id"),
    "npc_memories": ("session_id", "npc_id", "memory_id"),
    "npc_action_cards": ("session_id", "scene_id", "card_id"),
    "npc_events": ("session_id", "event_id"),
}


@dataclass(frozen=True, slots=True)
class RuntimeTablePolicy:
    authority: str = "table"  # table | json | hybrid
    hydrate_json_cache_after_table_write: bool = True
    use_json_only_when_table_rows_missing: bool = True


@dataclass(slots=True)
class RuntimeUpsertSpec:
    table: str
    unique_keys: tuple[str, ...]
    update_policy: str
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeUpsertPlan:
    specs: list[RuntimeUpsertSpec]

    def summary(self) -> dict[str, int]:
        return {spec.table: len(spec.rows) for spec in self.specs}


def build_runtime_upsert_plan(payload: Any) -> RuntimeUpsertPlan:
    """Build a DB-agnostic upsert plan from your runtime table payload object."""

    specs = [
        RuntimeUpsertSpec(
            table="npc_profiles",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_profiles"],
            update_policy="replace_profile_json",
            rows=list(getattr(payload, "profiles", []) or []),
        ),
        RuntimeUpsertSpec(
            table="npc_states",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_states"],
            update_policy="update_only_if_incoming_state_version_gte_existing",
            rows=list(getattr(payload, "states", []) or []),
        ),
        RuntimeUpsertSpec(
            table="npc_relationships",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_relationships"],
            update_policy="replace_relationship_json",
            rows=list(getattr(payload, "relationships", []) or []),
        ),
        RuntimeUpsertSpec(
            table="npc_memories",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_memories"],
            update_policy="insert_ignore_existing_memory_id",
            rows=list(getattr(payload, "memories", []) or []),
        ),
        RuntimeUpsertSpec(
            table="npc_action_cards",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_action_cards"],
            update_policy="update_only_if_incoming_based_on_turn_gte_existing",
            rows=list(getattr(payload, "action_cards", []) or []),
        ),
        RuntimeUpsertSpec(
            table="npc_events",
            unique_keys=RUNTIME_TABLE_UNIQUE_KEYS["npc_events"],
            update_policy="insert_ignore_existing_event_id",
            rows=list(getattr(payload, "events", []) or []),
        ),
    ]
    return RuntimeUpsertPlan(specs)


def should_hydrate_from_table_rows(
    *,
    table_rows_available: bool,
    json_snapshot_available: bool,
    policy: RuntimeTablePolicy | None = None,
) -> bool:
    """Return whether pre-turn should hydrate runtime from table rows."""

    policy = policy or RuntimeTablePolicy()
    if policy.authority == "table":
        return table_rows_available
    if policy.authority == "json":
        return False
    # hybrid mode
    if table_rows_available:
        return True
    return not json_snapshot_available
