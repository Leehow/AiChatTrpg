"""Framework streaming helper for the IC runner.

Extracted from `services.trpg_ic_runner.stream_ic_turn` (Phase 1D). This
module owns the SSE event generation around `run_trpg_turn`: it sets up
the structured-event filter, the contest and check marker streams, drives
the framework's async iterator, applies tail flushes plus marker
sanitization, parses structured events, and surfaces the EmptyReply
error when the framework returned no usable assistant reply. The runner
keeps its public `stream_ic_turn` signature and uses
`FrameworkStreamResult` to read back the values it needs for the
downstream persistence + auto-memory + turn-trace phases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agents.trpg.check_actor_adapter import build_actor_lookup_context
from agents.trpg.check_inline import CheckMarkerStream, replace_checks_in_text
from agents.trpg.contest_inline import ContestMarkerStream, replace_contests_in_text
from agents.trpg.framework import (
    BpSnapshotEvent,
    ContentDeltaEvent,
    DoneEvent,
    ErrorEvent,
    MarkerEvent,
    MetadataEvent,
    SideEffectEvent,
    ThinkingEvent,
    run_trpg_turn,
)
from agents.trpg.framework.models import SessionStateDiff
from orm.models import GameSession, Ruleset
from services.trpg_context.layered_prompt_projection import (
    compile_layered_prompt_context,
)
from services.trpg_ic.snapshots import (
    _bp123m_thinking_line,
    _ic_bp_snapshot_metadata,
)
from services.trpg_ic.state_diff import _runtime_check_spec_for_ruleset


__all__ = [
    "FrameworkStreamResult",
    "stream_framework_events",
]


@dataclass
class FrameworkStreamResult:
    """Collected state from one `stream_framework_events` run.

    The helper writes into these fields while yielding SSE event dicts.
    The runner reads them after consuming the generator to drive the
    rest of the turn (state-diff apply, persistence, auto-memory,
    turn-trace, etc.). `empty_reply=True` signals the caller that the
    EmptyReply error path already fired and it should `return`.
    """

    assistant_text: str = ""
    assistant_text_raw: str = ""
    thinking_lines: list[str] = field(default_factory=list)
    parsed_markers: list[dict[str, Any]] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    state_diff: SessionStateDiff | None = None
    inline_check_executions: list[Any] = field(default_factory=list)
    context_cache_projection: dict[str, Any] = field(default_factory=dict)
    bp_snapshot_metadata: dict[str, Any] = field(default_factory=dict)
    structured_parse: Any = None
    check_spec: dict[str, Any] = field(default_factory=dict)
    empty_reply: bool = False


async def stream_framework_events(
    *,
    inputs: Any,
    services: Any,
    session: GameSession,
    ruleset: Ruleset,
    ic_context: Any,
    provider: str,
    model_name: str,
    user_message_id: str | None,
    turn_id_hint: int,
    turn_marker: str,
    result: FrameworkStreamResult,
) -> AsyncIterator[dict[str, Any]]:
    """Drive `run_trpg_turn` and yield SSE-friendly event dicts.

    Side effects are confined to `result`: the runner sees the same SSE
    event order/shape it used to emit inline, and the per-turn locals
    (`assistant_text`, `assistant_text_raw`, `thinking_lines`,
    `parsed_markers`, `side_effects`, `state_diff`,
    `inline_check_executions`, `context_cache_projection`,
    `bp_snapshot_metadata`, `structured_parse`, `check_spec`) end up
    on the result object. If the framework yielded an ErrorEvent or
    finished with no usable assistant text, the helper yields the
    appropriate error event, sets `result.empty_reply = True`, and
    stops — the runner must `return` when it sees that flag.
    """

    check_spec = _runtime_check_spec_for_ruleset(ruleset)
    result.check_spec = check_spec
    contest_stream = ContestMarkerStream(check_spec)
    actor_lookup_context = build_actor_lookup_context(session)
    check_stream = CheckMarkerStream(
        check_spec,
        actor_context=actor_lookup_context,
        execution_sink=result.inline_check_executions,
    )
    from services.trpg_structured_events import (
        StructuredEventsStreamFilter,
        parse_structured_events,
        strip_structured_events,
    )
    structured_stream = StructuredEventsStreamFilter()
    rendered_content_parts: list[str] = []

    async for ev in run_trpg_turn(inputs, services):
        if isinstance(ev, MetadataEvent):
            yield {"type": "metadata", "metadata": dict(ev.payload)}
        elif isinstance(ev, ThinkingEvent):
            result.thinking_lines.append(ev.line)
            yield {"type": "thinking", "content": ev.line}
        elif isinstance(ev, BpSnapshotEvent):
            result.bp_snapshot_metadata = _ic_bp_snapshot_metadata(
                ev.snapshot,
                session,
                chat_until_message_id=user_message_id,
            )
            if ev.layered_prompt is not None:
                try:
                    result.context_cache_projection = compile_layered_prompt_context(
                        layered_prompt=ev.layered_prompt,
                        provider=provider,
                        model=model_name,
                        ruleset_id=str(ruleset.id),
                        campaign_id=str(session.id),
                        session_id=str(session.id),
                        scene_id=ic_context.scene_key or None,
                        turn_id=turn_marker,
                        chapter_id=ic_context.module_chapter_name or None,
                    ).metadata
                except Exception as _exc:
                    result.context_cache_projection = {
                        "error": f"{type(_exc).__name__}: {_exc}",
                        "projection": "layered_prompt_v1",
                    }
            bp123m_line = _bp123m_thinking_line(result.context_cache_projection)
            result.thinking_lines.append(bp123m_line)
            yield {"type": "thinking", "content": bp123m_line}
        elif isinstance(ev, ContentDeltaEvent):
            visible_delta = structured_stream.feed(ev.delta or "")
            if not visible_delta:
                continue
            contest_stream.feed(visible_delta)
            contest_out = contest_stream.drain()
            if contest_out:
                check_stream.feed(contest_out)
                rendered = check_stream.drain()
                if rendered:
                    rendered_content_parts.append(rendered)
                    yield {"type": "content", "content": rendered}
        elif isinstance(ev, MarkerEvent):
            m = ev.marker
            parsed = {
                "kind": str(getattr(m, "kind", "")),
                "args": dict(getattr(m, "args", {}) or {}),
                "body": str(getattr(m, "body", "") or ""),
            }
            result.parsed_markers.append(parsed)
            yield {"type": "marker", "marker": parsed}
        elif isinstance(ev, SideEffectEvent):
            result.side_effects.append({"kind": ev.kind, "payload": dict(ev.payload)})
            yield {
                "type": "side_effect",
                "kind": ev.kind, "payload": dict(ev.payload),
            }
        elif isinstance(ev, ErrorEvent):
            yield {
                "type": "error",
                "content": ev.message, "exc_type": ev.exc_type,
            }
            result.empty_reply = True
            return
        elif isinstance(ev, DoneEvent):
            result.assistant_text_raw = ev.result.assistant
            result.state_diff = ev.result.state_diff

    structured_tail = structured_stream.flush()
    if structured_tail:
        contest_stream.feed(structured_tail)
        contest_out = contest_stream.drain()
        if contest_out:
            check_stream.feed(contest_out)
            rendered = check_stream.drain()
            if rendered:
                rendered_content_parts.append(rendered)
                yield {"type": "content", "content": rendered}

    contest_tail = contest_stream.flush()
    if contest_tail:
        check_stream.feed(contest_tail)
        rendered = check_stream.drain()
        if rendered:
            rendered_content_parts.append(rendered)
            yield {"type": "content", "content": rendered}
    check_tail = check_stream.flush()
    if check_tail:
        rendered_content_parts.append(check_tail)
        yield {"type": "content", "content": check_tail}

    if rendered_content_parts:
        result.assistant_text = "".join(rendered_content_parts).strip()
    elif result.assistant_text_raw:
        result.assistant_text = replace_checks_in_text(
            replace_contests_in_text(result.assistant_text_raw, check_spec),
            check_spec,
            actor_context=actor_lookup_context,
            execution_sink=result.inline_check_executions,
        ).strip()

    # Unwrap markdown-wrapped markers (`**[CHECK ...]**`, `` `[TAKE_TIME]` ``)
    # and fix space/underscore typos (`[TAKE TIME]` → `[TAKE_TIME]`). The
    # streaming path's `CheckMarkerStream` requires an exact `[CHECK ` opener
    # to start buffering, so a bold-wrapped marker passes through verbatim
    # — sanitize lets us catch it here and run a second `replace_*_in_text`
    # pass to render those leakers as proper `[dice]` blocks.
    from services.trpg_marker_sanitize import sanitize_markers

    sanitized = sanitize_markers(result.assistant_text)
    if sanitized != result.assistant_text:
        result.assistant_text = replace_checks_in_text(
            replace_contests_in_text(sanitized, check_spec),
            check_spec,
            actor_context=actor_lookup_context,
            execution_sink=result.inline_check_executions,
        ).strip()

    structured_source = sanitize_markers(result.assistant_text_raw or result.assistant_text)
    result.structured_parse = parse_structured_events(
        structured_source,
        scene_id=ic_context.scene_key or "scene_unknown",
        turn_id=max(1, turn_id_hint),
    )
    result.assistant_text = strip_structured_events(result.assistant_text)

    if result.state_diff is None or not result.assistant_text:
        yield {
            "type": "error",
            "content": "framework returned no assistant reply",
            "exc_type": "EmptyReply",
        }
        result.empty_reply = True
        return
