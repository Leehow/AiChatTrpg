"""Memory-state writers used by `apply_post_turn_result_to_memory_state`."""

from __future__ import annotations

from typing import Any

from services.trpg_npc.models import MemoryRecord, RelationshipVector
from services.trpg_npc.optimization.memory_compaction import compact_npc_memories


def _write_relationships_v2(
    npc: dict[str, Any],
    *,
    npc_id: str,
    relationships: dict[str, RelationshipVector],
) -> int:
    if not relationships:
        return 0
    existing = npc.get("relationships_v2")
    bucket: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    count = 0
    for target_id, relationship in relationships.items():
        key = str(target_id or "").strip()
        if not key or key == npc_id or key == "gm":
            continue
        bucket[key] = relationship.to_dict()
        count += 1
    if count:
        npc["relationships_v2"] = bucket
    return count


def _append_memories_v2(
    npc: dict[str, Any],
    memories: list[MemoryRecord],
    *,
    memory_cap: int,
) -> tuple[int, int]:
    if not memories:
        return 0, 0
    existing_raw = npc.get("memories_v2")
    existing = [
        item for item in existing_raw
        if isinstance(item, dict)
    ] if isinstance(existing_raw, list) else []
    seen_ids = {
        str(item.get("memory_id") or "")
        for item in existing
        if item.get("memory_id")
    }
    added = 0
    for memory in memories:
        if memory.memory_id in seen_ids:
            continue
        item = memory.to_dict()
        item["content"] = str(item.get("content") or "")[:320]
        existing.append(item)
        seen_ids.add(memory.memory_id)
        added += 1
    cap = max(1, int(memory_cap or 20))
    recent_cap = min(8, cap)
    important_cap = max(0, cap - recent_cap)
    compacted = compact_npc_memories(
        existing,
        max_recent=recent_cap,
        max_important=important_cap,
        existing_archived_summary=(
            str(npc.get("memory_archive_summary_v2"))
            if npc.get("memory_archive_summary_v2")
            else None
        ),
    )
    npc["memories_v2"] = compacted.kept
    if compacted.archived_summary:
        npc["memory_archive_summary_v2"] = compacted.archived_summary
    return added, compacted.dropped_count
