"""Post-framework persistence/state phase of an IC turn.

Runs after `stream_framework_events` has produced the assistant reply, the
parsed markers, and the in-memory state diff. This module:

- Applies the framework's state diff to the session.
- Enhances player-known NPC labels and stamps new NPCs with the current scene.
- Parses + applies chatrpg-extension markers (TAKE_TIME / SET_OBJECTIVE /
  ADD_NOTE / name_reveal) and seeds `gm_meta`.
- Resolves spoken NPCs and ensures NPC assets (yields the `npc_assets`
  side_effect at the same point as the prior inline implementation).
- Annotates `[speak]` tags with stable NPC keys.
- Attaches context cache projection / BP snapshot / NPC runtime / structured
  events metadata to `gm_meta`, yielding the `structured_events` side_effect.
- Builds and persists authoritative state changes for the live turn, deriving
  `confirmed_state_change_ids` and the per-event map.
- Stashes pending checks metadata and the `npc_post_visible_work` envelope.
- Saves the GM message and records inline check logs against it.

Yields the same SSE side_effect events in the same order as before, and writes
every value the runner reads downstream into a mutable `PostStateResult`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from agents.trpg.speaker_resolver import annotate_speak_tags
from orm.models import GameSession
from services.trpg_check_logs import record_check_execution
from services.trpg_ic.framework_stream import FrameworkStreamResult
from services.trpg_ic.messages import _save_message
from services.trpg_ic.state_diff import _apply_state_diff, _memory_npcs
from services.trpg_ic_markers import (
    apply_chatrpg_markers,
    parse_chatrpg_markers,
)
from services.trpg_npc.assets import ensure_npc_assets
from services.trpg_pending_checks import find_pending_checks
from services.trpg_runtime.authoritative_turn_adapter import (
    build_state_changes_for_live_turn,
    persist_state_changes_for_turn,
)
from services.trpg_scene_runtime import (
    ensure_spoken_npcs_with_scene,
    stamp_new_npcs_with_scene,
)


@dataclass
class PostStateResult:
    """Mutable collector for values the runner reads after this phase."""

    assistant_text: str = ""
    diff_summary: dict[str, Any] = field(default_factory=dict)
    extension: Any = None
    extension_summary: dict[str, Any] | None = None
    gm_meta: dict[str, Any] = field(default_factory=dict)
    portrait_task_keys: list[str] = field(default_factory=list)
    confirmed_state_change_ids: tuple[str, ...] = ()
    confirmed_state_change_ids_by_event_id: dict[str, tuple[str, ...]] = field(
        default_factory=dict,
    )
    state_runtime_result: dict[str, Any] = field(default_factory=dict)
    state_changes_for_turn: tuple = ()
    pending_in_text: list[Any] = field(default_factory=list)
    npc_post_visible_work: dict[str, Any] = field(default_factory=dict)
    gm_message: Any = None
    check_refs: list[dict[str, Any]] = field(default_factory=list)


async def stream_post_state_phase(
    *,
    db: AsyncSession,
    session: GameSession,
    text: str,
    framework_result: FrameworkStreamResult,
    npc_runtime_read: dict[str, Any],
    provider: str,
    model_name: str,
    turn_id_hint: int,
    turn_marker: str,
    result: PostStateResult,
) -> AsyncIterator[dict[str, Any]]:
    """Run the post-framework persistence phase for one IC turn.

    Yields the same SSE side_effect events in the same order the inline
    implementation did; fills ``result`` with every value the runner reads
    after this phase returns. The runner stays responsible for the
    search-rules, auto-memory, narrative-compression, cache-metrics,
    turn-trace, background-task, and combat-auto-continuation sections.
    """

    assistant_text = framework_result.assistant_text
    parsed_markers = framework_result.parsed_markers
    side_effects = framework_result.side_effects
    state_diff = framework_result.state_diff
    inline_check_executions = framework_result.inline_check_executions
    context_cache_projection = framework_result.context_cache_projection
    bp_snapshot_metadata = framework_result.bp_snapshot_metadata
    structured_parse = framework_result.structured_parse
    check_spec = framework_result.check_spec
    thinking_lines = framework_result.thinking_lines

    diff_summary = _apply_state_diff(session, state_diff, parsed_markers=parsed_markers)

    # Upgrade any freshly-created NPC whose sync regex landed on a
    # generic "陌生人" / "unknown person" fallback. Runs after
    # _apply_state_diff so memory_state.npcs already contains the new
    # entries; idempotent for entries already specifically labelled.
    try:
        from services.trpg_npc import enhance_player_known_names

        npc_list = (
            session.memory_state.get("npcs")
            if isinstance(session.memory_state, dict) else None
        )
        if isinstance(npc_list, list) and npc_list:
            if await enhance_player_known_names(db, npc_list):
                flag_modified(session, "memory_state")
    except Exception as _exc:  # noqa: BLE001 - cosmetic, never bubble
        diff_summary["npc_label_enhance_error"] = str(_exc)

    # Tag freshly-created NPCs with the current scene key so future turns
    # in this scene render them as Active NPCs while later scenes' NPCs
    # drop out. Runs after _apply_state_diff so memory_state.npcs already
    # contains the new entries.
    try:
        npcs_stamped = stamp_new_npcs_with_scene(
            session, parsed_markers, turn_marker=str(session.id)[:8],
        )
    except Exception as _exc:
        npcs_stamped = 0
    if npcs_stamped:
        diff_summary["npcs_scene_stamped"] = npcs_stamped

    # chatrpg-extension markers (TAKE_TIME / SET_OBJECTIVE / ADD_NOTE /
    # name_reveal). Framework's parser doesn't know these; we extract
    # them from raw assistant text and apply to module_state /
    # memory_state separately.
    #
    # IMPORTANT — apply BEFORE `ensure_spoken_npcs_with_scene`. When
    # the same turn contains `[name_reveal]` plus a `[speak]<true_name>`,
    # speaker resolution must see the post-flip roster (where
    # ``player_known_name`` already equals the true name) so it matches
    # the existing NPC instead of spawning a stub `npc_spoken_*` and
    # orphaning the original entry.
    extension = parse_chatrpg_markers(assistant_text)
    gm_meta: dict[str, Any] = {
        "trpg_mode": "ic",
        "provider": provider,
        "model": model_name,
        "thinking_steps": thinking_lines,
        "parsed_markers": parsed_markers,
        "side_effects": side_effects,
        "diff_summary": diff_summary,
    }
    extension_summary = apply_chatrpg_markers(
        session, extension, gm_message_metadata=gm_meta,
    )
    if extension_summary:
        gm_meta["extension_summary"] = extension_summary

    try:
        spoken_npc_keys = await ensure_spoken_npcs_with_scene(
            session,
            assistant_text,
            turn_marker=str(session.id)[:8],
        )
    except Exception as _exc:
        spoken_npc_keys = []
        diff_summary["spoken_npcs_error"] = str(_exc)
    if spoken_npc_keys:
        diff_summary["spoken_npcs_created"] = spoken_npc_keys

    portrait_task_keys: list[str] = []
    try:
        async with db.begin_nested():
            asset_summary = await ensure_npc_assets(db, session)
    except Exception as _exc:
        asset_summary = None
        diff_summary["npc_assets_error"] = str(_exc)
    if asset_summary is not None:
        asset_payload = asset_summary.to_dict()
        diff_summary["npc_assets"] = asset_payload
        portrait_task_keys = list(asset_summary.portraits_queued)
        if asset_summary.voices_assigned or portrait_task_keys:
            yield {
                "type": "side_effect",
                "kind": "npc_assets",
                "payload": asset_payload,
            }

    # Add stable NPC keys to `[speak]` tags where possible so the frontend can
    # render portraits / future voices by id instead of fuzzy label matching.
    assistant_text = annotate_speak_tags(assistant_text, _memory_npcs(session))

    if context_cache_projection:
        gm_meta["context_cache_projection"] = {
            "cache_key": context_cache_projection.get("cache_key", ""),
            "prefix_hash": context_cache_projection.get("prefix_hash", ""),
            "visibility_signature": context_cache_projection.get("visibility_signature", ""),
            "block_version_ids": context_cache_projection.get("block_version_ids", []),
            "block_count": context_cache_projection.get("block_count", 0),
            "token_estimate": context_cache_projection.get("token_estimate", 0),
            "projection": context_cache_projection.get("projection", ""),
            **(
                {"error": context_cache_projection["error"]}
                if context_cache_projection.get("error") else {}
            ),
        }
    if bp_snapshot_metadata:
        gm_meta["bp_snapshot"] = bp_snapshot_metadata
    if npc_runtime_read:
        gm_meta["npc_runtime_read"] = npc_runtime_read
    if structured_parse.events or structured_parse.errors:
        gm_meta["structured_events"] = structured_parse.to_metadata()
        yield {
            "type": "side_effect",
            "kind": "structured_events",
            "payload": {
                "count": len(structured_parse.events),
                "errors": list(structured_parse.errors),
            },
        }

    confirmed_state_change_ids: tuple[str, ...] = ()
    confirmed_state_change_ids_by_event_id: dict[str, tuple[str, ...]] = {}
    state_runtime_result: dict[str, Any] = {}
    state_changes_for_turn: tuple = ()
    try:
        state_changes_for_turn = build_state_changes_for_live_turn(
            session=session,
            turn_id=turn_marker,
            structured_events=structured_parse.events,
            parsed_markers=parsed_markers,
            extension=extension,
            assistant_text=assistant_text,
            player_message=text,
        )
        async with db.begin_nested():
            state_runtime_result = await persist_state_changes_for_turn(
                db,
                session,
                campaign_id=str(session.id),
                turn_id=turn_marker,
                changes=state_changes_for_turn,
            )
        confirmed_state_change_ids = tuple(
            str(cid)
            for cid in state_runtime_result.get("confirmed_state_change_ids", [])
            if str(cid)
        )
        confirmed_set = set(confirmed_state_change_ids)
        event_change_map: dict[str, list[str]] = {}
        for change in state_changes_for_turn:
            source_event_id = str((getattr(change, "metadata", {}) or {}).get("source_event_id") or "")
            if source_event_id and change.change_id in confirmed_set:
                event_change_map.setdefault(source_event_id, []).append(change.change_id)
        confirmed_state_change_ids_by_event_id = {
            event_id: tuple(ids) for event_id, ids in event_change_map.items()
        }
        if confirmed_state_change_ids_by_event_id:
            state_runtime_result["confirmed_state_change_ids_by_event_id"] = {
                event_id: list(ids) for event_id, ids in confirmed_state_change_ids_by_event_id.items()
            }
    except Exception as _exc:
        state_runtime_result = {"error": f"{type(_exc).__name__}: {_exc}"}
    if state_runtime_result:
        gm_meta["state_runtime"] = state_runtime_result

    # Stash structured pending checks alongside the placeholder text so the
    # frontend can render the "投出" card from metadata without re-parsing
    # the message body. Each entry carries id/skill/value/difficulty/reason
    # plus a `resolved=False` flag the resolve endpoint flips.
    pending_in_text = find_pending_checks(assistant_text)
    if pending_in_text:
        gm_meta["pending_checks"] = [p.to_metadata() for p in pending_in_text]

    npc_post_visible_work = {
        "scheduled": True,
        "mode": "silent_background",
        "turn_id": max(1, turn_id_hint),
    }
    gm_meta["npc_post_visible_work"] = npc_post_visible_work
    diff_summary["npc_post_visible_work"] = npc_post_visible_work

    gm_message = await _save_message(
        db, session.id, "assistant", assistant_text,
        metadata=gm_meta, session=session,
    )
    # Flush so the messages row is in Postgres BEFORE we insert any
    # check_logs that FK-reference its id. Without this, an implicit
    # flush at commit time can send the check_logs INSERT first and
    # raise ForeignKeyViolation against messages.id.
    if gm_message is not None:
        await db.flush()
    check_refs: list[dict[str, Any]] = []
    if gm_message is not None and inline_check_executions:
        for execution in inline_check_executions:
            check_log = record_check_execution(
                db,
                session,
                execution,
                message_id=gm_message.id,
                source="inline_check",
                runtime_spec=check_spec,
            )
            check_refs.append({
                "id": check_log.id,
                "procedure_id": check_log.procedure_id,
                "engine": check_log.engine,
                "seed": check_log.seed,
                "source": check_log.source,
                "rule_consequences": (check_log.result_json or {}).get("rule_consequences") or [],
            })
        if check_refs:
            meta = dict(gm_message.metadata_json or {})
            meta["check_logs"] = check_refs
            gm_message.metadata_json = meta
            flag_modified(gm_message, "metadata_json")

    result.assistant_text = assistant_text
    result.diff_summary = diff_summary
    result.extension = extension
    result.extension_summary = extension_summary
    result.gm_meta = gm_meta
    result.portrait_task_keys = portrait_task_keys
    result.confirmed_state_change_ids = confirmed_state_change_ids
    result.confirmed_state_change_ids_by_event_id = confirmed_state_change_ids_by_event_id
    result.state_runtime_result = state_runtime_result
    result.state_changes_for_turn = state_changes_for_turn
    result.pending_in_text = pending_in_text
    result.npc_post_visible_work = npc_post_visible_work
    result.gm_message = gm_message
    result.check_refs = check_refs
