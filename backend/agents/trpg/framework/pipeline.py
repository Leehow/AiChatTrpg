"""run_trpg_turn — the single top-level entrypoint.

Phase 1: skeleton orchestrator. The structure below is the contract; phase
implementations are NotImplementedError stubs until Phase 3.

Caller pattern:

    async for event in run_trpg_turn(inputs, services):
        match event:
            case ContentDeltaEvent(delta=d): ...
            case ThinkingEvent(line=l): ...
            case DoneEvent(result=r):
                persist(r.state_diff)
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .events import (
    BpSnapshotEvent,
    ContentDeltaEvent,
    DoneEvent,
    ErrorEvent,
    MarkerEvent,
    MetadataEvent,
    SideEffectEvent,
    ThinkingEvent,
    TurnEvent,
)
from .models import TrpgServices, TurnInputs, TurnResult
from .modes import select_mode
from .phases.generate import _ContentChunk, _Final, generate
from .phases.postprocess import postprocess
from .phases.preprocess import preprocess


async def run_trpg_turn(
    inputs: TurnInputs,
    services: TrpgServices,
) -> AsyncIterator[TurnEvent]:
    """Drive one TRPG turn end-to-end. Yields TurnEvent stream; final
    DoneEvent carries the structured TurnResult."""
    try:
        mode = select_mode(inputs.session_state, inputs.mode_hint)
        yield MetadataEvent(payload={"mode": mode.value})

        prep = await preprocess(inputs, services)
        for line in prep.thinking_lines:
            yield ThinkingEvent(line=line)
        yield BpSnapshotEvent(
            snapshot=prep.bp_snapshot,
            layered_prompt=prep.layered_prompt,
            metadata=dict(prep.metadata),
        )

        final_reply = None
        async for ev in generate(inputs, prep, services):
            if isinstance(ev, _ContentChunk):
                yield ContentDeltaEvent(delta=ev.delta)
            elif isinstance(ev, _Final):
                final_reply = ev.reply

        if final_reply is None:
            yield ErrorEvent(message="generate phase produced no final reply",
                             exc_type="MissingFinalReply")
            return

        post = await postprocess(inputs, final_reply, services)
        for marker in post.parsed_markers:
            yield MarkerEvent(marker=marker)
        for effect in post.side_effects:
            yield SideEffectEvent(
                kind=str(effect.get("kind") or "unknown"),
                payload=effect,
            )

        result = TurnResult(
            assistant=final_reply.text,
            metadata={
                **prep.metadata,
                **final_reply.metadata,
                "parsed_markers": list(post.parsed_markers),
                "side_effects": list(post.side_effects),
            },
            state_diff=post.state_diff,
            thinking_events=list(prep.thinking_lines),
            bp_snapshot=prep.bp_snapshot,
        )
        yield DoneEvent(result=result)

    except NotImplementedError as exc:
        # Expected during Phase 1 — surface as a structured event so callers
        # don't blow up while wiring the plumbing.
        yield ErrorEvent(message=str(exc), exc_type="NotImplementedError")
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        yield ErrorEvent(message=str(exc), exc_type=type(exc).__name__)
