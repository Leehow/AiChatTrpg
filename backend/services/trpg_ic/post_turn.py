"""Post-GM auto-memory / compression / cache / turn-trace phase of an IC turn.

Runs after `stream_post_state_phase` has saved the GM message and after the
runner's `[SEARCH_RULES ...]` lookup has appended any rule excerpts. This
module:

- Runs the auto-memory pass (structured events preferred, prose scanner
  fallback), commits memory proposals, projects to legacy state, and patches
  `gm_message.metadata_json["auto_memory_v2"]`. Yields the `auto_memory`
  side_effect (or the `[auto-memory] skipped …` thinking) at the same point
  as before.
- Compresses aged-out narrative when threshold met, yielding the
  `narrative_compressed` side_effect at the same point as before.
- Computes actual cache metrics, appends the `[cache]` thinking line, and
  patches `gm_message.metadata_json["cache_metrics"]` /
  `metadata_json["thinking_steps"]`.
- Persists the turn trace and patches `gm_message.metadata_json["turn_trace"]`
  on success; writes `diff_summary["turn_trace_error"]` on failure.

Yields the same SSE events in the same order as before, and exposes downstream
locals (`auto_summary`, `auto_memory_v2`, `compression`) on a mutable
`PostTurnResult`. `diff_summary`, `thinking_lines`, and `gm_message` are
mutated in place via the shared `post_state_result` / `framework_result`
references the runner already holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_auto_memory import (
    build_auto_memory_proposals,
    build_structured_event_auto_memory_result,
    build_structured_event_memory_proposals,
    run_auto_memory_update,
)
from services.trpg_ic.framework_stream import FrameworkStreamResult
from services.trpg_ic.llm_adapter import (
    ChatrpgLlmAdapter,
    _llm_cache_metrics_from_usage,
)
from services.trpg_ic.messages import _RECENT_HISTORY_LIMIT
from services.trpg_ic.post_state import PostStateResult
from services.trpg_ic.snapshots import _cache_thinking_line
from services.trpg_memory.legacy_projection import (
    project_committed_auto_memory_to_legacy_state,
)
from services.trpg_memory.runtime_store import (
    commit_memory_proposals,
    memory_item_to_dict,
)
from services.trpg_narrative_compression import maybe_compress_narrative
from services.trpg_runtime.runtime_store import save_turn_trace
from services.trpg_runtime.turn_trace import TurnTrace


_EMPTY_AUTO_SUMMARY: dict[str, Any] = {
    "events": 0,
    "plot_threads_upserted": 0,
    "plot_threads_added": 0,
    "discoveries": 0,
}


@dataclass
class PostTurnResult:
    """Mutable collector for the values the runner reads after this phase."""

    auto_summary: dict[str, Any] = field(
        default_factory=lambda: dict(_EMPTY_AUTO_SUMMARY),
    )
    auto_memory_v2: dict[str, Any] | None = None
    compression: Any = None


async def stream_post_turn_phase(
    *,
    db: AsyncSession,
    session: GameSession,
    text: str,
    framework_result: FrameworkStreamResult,
    post_state_result: PostStateResult,
    npc_runtime_read: dict[str, Any],
    llm: ChatrpgLlmAdapter,
    provider: str,
    model_name: str,
    turn_marker: str,
    result: PostTurnResult,
) -> AsyncIterator[dict[str, Any]]:
    """Drain the post-GM auto-memory → compression → cache → turn-trace
    sequence, yielding SSE events in the same order/shape as the prior inline
    runner implementation. Mutates `post_state_result.gm_message.metadata_json`,
    `post_state_result.diff_summary`, and `framework_result.thinking_lines`
    in place; collects the produced summaries on `result`."""

    assistant_text = post_state_result.assistant_text
    diff_summary = post_state_result.diff_summary
    extension = post_state_result.extension
    extension_summary = post_state_result.extension_summary
    gm_meta = post_state_result.gm_meta
    confirmed_state_change_ids = post_state_result.confirmed_state_change_ids
    confirmed_state_change_ids_by_event_id = (
        post_state_result.confirmed_state_change_ids_by_event_id
    )
    state_runtime_result = post_state_result.state_runtime_result
    npc_post_visible_work = post_state_result.npc_post_visible_work
    gm_message = post_state_result.gm_message
    check_refs = post_state_result.check_refs
    assistant_text_raw = framework_result.assistant_text_raw
    thinking_lines = framework_result.thinking_lines
    parsed_markers = framework_result.parsed_markers
    side_effects = framework_result.side_effects
    context_cache_projection = framework_result.context_cache_projection
    structured_parse = framework_result.structured_parse

    # Auto-memory pass. Prefer structured events when the GM provided them;
    # otherwise fall back to the older small-model prose scanner. Structured
    # event proposals keep their original visibility; hidden discovery events
    # can become GM_ONLY memories but never PARTY_KNOWN player discoveries.
    structured_memory_proposals: list[Any] = []
    try:
        if structured_parse.events:
            yield {"type": "thinking", "content": "[auto-memory] using structured events…"}
            auto_result = build_structured_event_auto_memory_result(structured_parse.events)
            structured_memory_proposals = build_structured_event_memory_proposals(
                structured_parse.events,
                turn_marker=turn_marker,
                confirmed_state_change_ids_by_event_id=confirmed_state_change_ids_by_event_id,
            )
        else:
            yield {"type": "thinking", "content": "[auto-memory] scanning reply…"}
            async with db.begin_nested():
                auto_result = await run_auto_memory_update(
                    db, session,
                    gm_content=assistant_text,
                    player_message=text,
                )
    except Exception as _exc:
        from services.trpg_auto_memory import AutoMemoryResult
        auto_result = AutoMemoryResult(skipped_reason=f"runtime_error: {_exc}")
        structured_memory_proposals = []

    auto_summary: dict[str, Any] = dict(_EMPTY_AUTO_SUMMARY)
    auto_memory_v2: dict[str, Any] | None = None
    try:
        proposals = structured_memory_proposals or build_auto_memory_proposals(
            auto_result,
            player_message=text,
            gm_content=assistant_text,
            turn_marker=turn_marker,
        )
        if proposals:
            state_failed = bool(
                isinstance(state_runtime_result, dict)
                and (state_runtime_result.get("error") or state_runtime_result.get("errors"))
            )
            if state_failed:
                auto_memory_v2 = {
                    "proposed": len(proposals),
                    "committed": 0,
                    "reinforced": 0,
                    "rejected": [
                        {
                            "code": "state_runtime_failed",
                            "message": "state runtime failed; canonical memory commit was skipped for this turn",
                            "severity": "error",
                        }
                    ],
                    "duplicate_noops": 0,
                    "memory_ids": [],
                    "reinforced_memory_ids": [],
                    "confirmed_state_change_ids": list(confirmed_state_change_ids),
                    "postprocess_status": "partial_state_failed",
                }
            else:
                async with db.begin_nested():
                    commit_result = await commit_memory_proposals(
                        db,
                        session,
                        proposals,
                        transcript_text="\n".join(part for part in (text, assistant_text) if part),
                        confirmed_state_change_ids=confirmed_state_change_ids,
                    )
                projected_items = [*commit_result.committed, *getattr(commit_result, "reinforced", ())]
                auto_summary = project_committed_auto_memory_to_legacy_state(
                    session,
                    projected_items,
                    turn_marker=turn_marker,
                )
                auto_memory_v2 = {
                    "proposed": len(proposals),
                    "committed": len(commit_result.committed),
                    "reinforced": len(getattr(commit_result, "reinforced", ())),
                    "rejected": [
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "severity": issue.severity,
                        }
                        for issue in commit_result.rejected
                    ],
                    "duplicate_noops": len(commit_result.duplicate_noops),
                    "memory_ids": [item.memory_id for item in commit_result.committed],
                    "reinforced_memory_ids": [item.memory_id for item in getattr(commit_result, "reinforced", ())],
                    "confirmed_state_change_ids": list(confirmed_state_change_ids),
                    "postprocess_status": "complete" if not commit_result.rejected else "memory_with_rejections",
                }
                if gm_message is not None:
                    meta = dict(gm_message.metadata_json or {})
                    meta["auto_memory_v2"] = {
                        **auto_memory_v2,
                        "committed_items": [
                            memory_item_to_dict(item)
                            for item in commit_result.committed
                        ],
                        "reinforced_items": [
                            memory_item_to_dict(item)
                            for item in getattr(commit_result, "reinforced", ())
                        ],
                    }
                    gm_message.metadata_json = meta
                    flag_modified(gm_message, "metadata_json")
        elif not auto_result.is_empty():
            auto_memory_v2 = {"proposed": 0, "committed": 0, "reinforced": 0, "rejected": []}
    except Exception as _exc:
        auto_memory_v2 = {"error": f"{type(_exc).__name__}: {_exc}"}

    result.auto_summary = auto_summary
    result.auto_memory_v2 = auto_memory_v2

    if not auto_result.is_empty():
        yield {
            "type": "side_effect",
            "kind": "auto_memory",
            "payload": {
                "events": auto_result.events,
                "plot_threads": auto_result.plot_threads,
                "discoveries": auto_result.discoveries,
                "summary": auto_summary,
                "memory_v2": auto_memory_v2,
            },
        }
    elif auto_result.skipped_reason:
        yield {
            "type": "thinking",
            "content": f"[auto-memory] skipped: {auto_result.skipped_reason}",
        }

    # NPC Runtime V2 warm/table-authority work now runs after the visible GM
    # reply is saved and committed. The current turn records that the silent
    # background job was scheduled; the next turn reads the warmed tables.

    # Rolling narrative summary: when the IC history grows past the live
    # window, compress aged-out messages into `session.narrative_summary` so
    # the GM keeps awareness of earlier beats. Only fires when threshold met
    # — most turns skip this entirely. Failures fall back to a deterministic
    # concat-and-trim summary.
    try:
        async with db.begin_nested():
            compression = await maybe_compress_narrative(
                db, session, recent_keep=_RECENT_HISTORY_LIMIT,
            )
    except Exception as _exc:
        from services.trpg_narrative_compression import CompressionResult
        compression = CompressionResult(skipped_reason=f"runtime_error: {_exc}")

    result.compression = compression

    if compression.ran:
        yield {
            "type": "side_effect",
            "kind": "narrative_compressed",
            "payload": {
                "dropped_count": compression.dropped_count,
                "new_summary_chars": compression.new_summary_chars,
                "previous_summary_chars": compression.previous_summary_chars,
                "new_last_summarized": compression.new_last_summarized,
            },
        }

    actual_cache_metrics = _llm_cache_metrics_from_usage(
        provider=provider,
        model=model_name,
        usage=getattr(llm, "last_usage", None),
    )
    cache_line = _cache_thinking_line(actual_cache_metrics)
    if cache_line:
        thinking_lines.append(cache_line)
        yield {"type": "thinking", "content": cache_line}
    if gm_message is not None:
        meta = dict(gm_message.metadata_json or {})
        meta["cache_metrics"] = actual_cache_metrics
        if cache_line:
            existing_steps = [
                str(step)
                for step in (meta.get("thinking_steps") or [])
                if str(step)
            ]
            if not any(step.startswith("[cache]") for step in existing_steps):
                existing_steps.append(cache_line)
            meta["thinking_steps"] = existing_steps
        gm_message.metadata_json = meta
        flag_modified(gm_message, "metadata_json")

    try:
        async with db.begin_nested():
            trace_row = await save_turn_trace(
                db,
                session,
                TurnTrace(
                    turn_id=turn_marker,
                    campaign_id=str(session.id),
                    player_input=text,
                    model_raw_output={
                        "assistant": assistant_text,
                        "assistant_raw": assistant_text_raw,
                    },
                    parsed_contract_summary={
                        "message_id": getattr(gm_message, "id", None),
                        "marker_count": len(parsed_markers),
                        "parsed_markers": parsed_markers,
                        "side_effect_count": len(side_effects),
                        "diff_summary": diff_summary,
                        "extension_summary": extension_summary,
                        "structured_events": structured_parse.to_metadata(),
                        "state_runtime": state_runtime_result,
                        "context_cache_projection": context_cache_projection,
                        "pending_checks": gm_meta.get("pending_checks") or [],
                        "check_logs": check_refs,
                        "auto_memory_summary": auto_summary,
                        "auto_memory_v2": auto_memory_v2 or {},
                        "npc_runtime_read": npc_runtime_read,
                        "npc_post_visible_work": npc_post_visible_work,
                        "narrative_compression": {
                            "ran": compression.ran,
                            "skipped_reason": compression.skipped_reason,
                            "dropped_count": compression.dropped_count,
                            "new_summary_chars": compression.new_summary_chars,
                            "previous_summary_chars": compression.previous_summary_chars,
                            "new_last_summarized": compression.new_last_summarized,
                        },
                        "search_rules_count": len(extension.search_rules_queries),
                    },
                    state_change_ids=confirmed_state_change_ids,
                    memory_proposal_count=int((auto_memory_v2 or {}).get("proposed") or 0),
                    committed_memory_ids=tuple(
                        str(mid)
                        for mid in (auto_memory_v2 or {}).get("memory_ids", [])
                        if str(mid)
                    ),
                    rejected_memory_count=len((auto_memory_v2 or {}).get("rejected") or []),
                    audit_warnings=tuple(
                        [
                            *(
                                [{"error": str((auto_memory_v2 or {}).get("error"))}]
                                if (auto_memory_v2 or {}).get("error") else []
                            ),
                            *(
                                [{"context_cache_projection_error": str(context_cache_projection.get("error"))}]
                                if context_cache_projection.get("error") else []
                            ),
                            *(
                                [{"state_runtime_error": str(state_runtime_result.get("error"))}]
                                if isinstance(state_runtime_result, dict) and state_runtime_result.get("error") else []
                            ),
                            *(
                                [{"state_runtime_errors": list(state_runtime_result.get("errors") or [])}]
                                if isinstance(state_runtime_result, dict) and state_runtime_result.get("errors") else []
                            ),
                        ]
                    ),
                    cache_metrics={
                        **actual_cache_metrics,
                        "thinking_count": len(thinking_lines),
                        "context_projection": context_cache_projection.get("projection", ""),
                        "context_block_count": context_cache_projection.get("block_count", 0),
                        "context_prefix_block_count": context_cache_projection.get("prefix_block_count", 0),
                        "context_pinned_block_count": context_cache_projection.get("pinned_block_count", 0),
                        "context_dynamic_block_count": context_cache_projection.get("dynamic_block_count", 0),
                        "context_token_estimate": context_cache_projection.get("token_estimate", 0),
                    },
                    context_cache_key=str(context_cache_projection.get("cache_key") or ""),
                    context_prefix_hash=str(context_cache_projection.get("prefix_hash") or ""),
                    retrieved_context_block_ids=tuple(
                        str(block_id)
                        for block_id in context_cache_projection.get("block_version_ids", [])
                        if str(block_id)
                    ),
                    visibility_signature=str(context_cache_projection.get("visibility_signature") or ""),
                ),
            )
        if gm_message is not None:
            meta = dict(gm_message.metadata_json or {})
            meta["turn_trace"] = {
                "id": trace_row.id,
                "turn_id": trace_row.turn_id,
            }
            gm_message.metadata_json = meta
            flag_modified(gm_message, "metadata_json")
    except Exception as _exc:
        diff_summary["turn_trace_error"] = f"{type(_exc).__name__}: {_exc}"
