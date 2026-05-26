"""NPC memory compaction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .common import clamp, get_value, to_plain_data


@dataclass(slots=True)
class MemoryCompactionResult:
    kept: list[dict[str, Any]]
    archived_summary: str | None
    dropped_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "archived_summary": self.archived_summary,
            "dropped_count": self.dropped_count,
        }


def _memory_sort_key(memory: dict[str, Any]) -> tuple[float, int, str]:
    importance = clamp(memory.get("importance", 0.0), 0.0, 1.0)
    turn_id = memory.get("turn_id")
    try:
        turn = int(turn_id)
    except (TypeError, ValueError):
        turn = 0
    memory_id = str(memory.get("memory_id", ""))
    return (importance, turn, memory_id)


def compact_npc_memories(
    memories: list[Any],
    *,
    max_recent: int = 8,
    max_important: int = 16,
    existing_archived_summary: str | None = None,
) -> MemoryCompactionResult:
    """Keep recent and important NPC memories while producing a compact archive.

    This is safe to run after ``warm_npc_action_board_after_turn`` before writing
    to session JSON.  Table rows may retain all memories if you prefer; the prompt
    snapshot should stay compact.
    """

    plain_memories = [m for m in (to_plain_data(memories) or []) if isinstance(m, dict)]
    if not plain_memories:
        return MemoryCompactionResult([], existing_archived_summary, 0)

    # Deduplicate by memory_id, keeping the last occurrence.
    by_id: dict[str, dict[str, Any]] = {}
    no_id: list[dict[str, Any]] = []
    for idx, memory in enumerate(plain_memories):
        memory_id = str(memory.get("memory_id") or "")
        if memory_id:
            by_id[memory_id] = memory
        else:
            memory["memory_id"] = f"anonymous_memory_{idx}"
            no_id.append(memory)
    deduped = list(by_id.values()) + no_id

    recent = sorted(
        deduped,
        key=lambda m: int(m.get("turn_id", 0) or 0),
        reverse=True,
    )[:max_recent]
    important = sorted(deduped, key=_memory_sort_key, reverse=True)[:max_important]

    keep_by_id: dict[str, dict[str, Any]] = {}
    for memory in recent + important:
        keep_by_id[str(memory.get("memory_id"))] = memory
    kept = list(keep_by_id.values())
    kept.sort(key=_memory_sort_key, reverse=True)

    kept_ids = set(keep_by_id)
    dropped = [m for m in deduped if str(m.get("memory_id")) not in kept_ids]
    if not dropped:
        return MemoryCompactionResult(kept, existing_archived_summary, 0)

    fragments: list[str] = []
    if existing_archived_summary:
        fragments.append(existing_archived_summary.strip())
    summarized_items = []
    for memory in sorted(dropped, key=_memory_sort_key, reverse=True)[:8]:
        content = str(memory.get("content") or memory.get("summary") or "").strip()
        if content:
            summarized_items.append(content[:120])
    if summarized_items:
        fragments.append("被折叠的旧记忆摘要：" + "；".join(summarized_items))
    archived_summary = "\n".join(fragments).strip()[:2000] if fragments else None
    return MemoryCompactionResult(kept, archived_summary, len(dropped))
