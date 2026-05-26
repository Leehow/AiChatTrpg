"""IC turn snapshot metadata + thinking-line formatters.

Extracted from `services.trpg_ic_runner` (Phase 1B). All three helpers are
formatting / shaping pure functions; they own no state and do not touch the
DB. Behavior, signatures, and emitted strings are unchanged.
"""

from __future__ import annotations

from typing import Any

from orm.models import GameSession
from services.trpg_ic.llm_adapter import _int_or_none
from services.trpg_ic.messages import _IC_PHASE, _json_ready


def _ic_bp_snapshot_metadata(
    snapshot: Any,
    session: GameSession,
    *,
    chat_until_message_id: str | None,
) -> dict[str, Any]:
    """Store the IC BP2/BP3 snapshot in the same shape the debug panel reads."""

    bp2 = getattr(snapshot, "bp2", None)
    bp3 = getattr(snapshot, "bp3", None)
    pc = getattr(bp3, "pc", None) if bp3 is not None else None
    memory_state: dict[str, Any] = {
        "scenes": _json_ready(getattr(bp2, "scenes", []) or []),
        "npcs": _json_ready(getattr(bp2, "npcs", []) or []),
        "plot_threads": _json_ready(getattr(bp2, "plot_threads", []) or []),
        "world_facts": _json_ready(getattr(bp2, "world_facts", []) or []),
    }
    active_chapter = getattr(bp2, "active_module_chapter", None) if bp2 is not None else None
    if active_chapter:
        memory_state["active_module_chapter"] = _json_ready(active_chapter)

    module_state = (
        dict(session.module_state)
        if isinstance(session.module_state, dict) else {}
    )
    return {
        "source_phase": _IC_PHASE,
        "chat_until_message_id": chat_until_message_id,
        "memory_state": memory_state,
        "narrative_summary": str(
            (getattr(bp2, "narrative_summary", "") if bp2 is not None else "")
            or session.narrative_summary
            or ""
        ),
        "pc": _json_ready(pc) if isinstance(pc, dict) else None,
        "draft_card": None,
        "ready": bool(pc),
        "dice_history": _json_ready(list(session.dice_history or [])),
        "module_state": _json_ready(module_state),
        "framework": {
            "active_npcs": _json_ready(getattr(bp3, "active_npcs", []) or []),
            "time_context": str(getattr(bp3, "time_context", "") or ""),
            "dice_pool_summary": str(getattr(bp3, "dice_pool_summary", "") or ""),
            "rag_hits": _json_ready(getattr(bp3, "rag_hits", []) or []),
            "chat_history_used": int(getattr(bp3, "chat_history_used", 0) or 0),
            "user_message_chars": len(str(getattr(bp3, "user_message", "") or "")),
        },
    }


def _bp123m_thinking_line(projection: dict[str, Any]) -> str:
    if not projection:
        return "[BP123M] snapshot=ready | projection=missing"
    if projection.get("error"):
        return (
            "[BP123M] snapshot=ready | "
            f"projection={projection.get('projection') or 'layered_prompt_v1'} | "
            f"error={str(projection.get('error') or '')[:160]}"
        )
    block_count = _int_or_none(projection.get("block_count")) or 0
    token_estimate = _int_or_none(projection.get("token_estimate")) or 0
    prefix_blocks = _int_or_none(projection.get("prefix_block_count")) or 0
    pinned_blocks = _int_or_none(projection.get("pinned_block_count")) or 0
    dynamic_blocks = _int_or_none(projection.get("dynamic_block_count")) or 0
    prefix_hash = str(projection.get("prefix_hash") or "")[:12]
    visibility = str(projection.get("visibility_signature") or "")[:12]
    return (
        "[BP123M] snapshot=ready | "
        f"projection={projection.get('projection') or 'layered_prompt_v1'} | "
        f"blocks={block_count} | prefix={prefix_blocks} | "
        f"pinned={pinned_blocks} | dynamic={dynamic_blocks} | "
        f"tokens={token_estimate} | hash={prefix_hash} | visibility={visibility}"
    )


def _cache_thinking_line(metrics: dict[str, Any]) -> str:
    provider = str(metrics.get("prompt_provider") or "?")
    model = str(metrics.get("prompt_model") or "?")
    if not metrics.get("usage_available"):
        return f"[cache] provider={provider} model={model} | usage=unavailable"

    input_tokens = _int_or_none(metrics.get("input_tokens")) or 0
    output_tokens = _int_or_none(metrics.get("output_tokens")) or 0
    cached_tokens = _int_or_none(metrics.get("cached_tokens")) or 0
    ratio = metrics.get("cache_hit_ratio")
    try:
        ratio_text = f"{float(ratio) * 100:.1f}%" if ratio is not None else "?"
    except (TypeError, ValueError):
        ratio_text = "?"
    return (
        f"[cache] provider={provider} model={model} | "
        f"input={input_tokens} | output={output_tokens} | "
        f"cached={cached_tokens} | hit={ratio_text}"
    )


__all__ = [
    "_ic_bp_snapshot_metadata",
    "_bp123m_thinking_line",
    "_cache_thinking_line",
]
