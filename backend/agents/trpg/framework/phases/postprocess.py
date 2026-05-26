"""Postprocess phase — parses markers in the reply, applies them to a
SessionStateDiff, and triggers multimedia side effects.

Multimedia errors are intentionally swallowed: a TTS / portrait failure must
not block the turn from persisting. They surface as side_effects entries with
`error` set, so callers can log if they care."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..markers import ParsedMarker, apply_markers, parse_markers
from ..models import SessionStateDiff, TrpgServices, TurnInputs
from .generate import FinalReply


@dataclass
class PostprocessOutput:
    state_diff: SessionStateDiff
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    parsed_markers: list[ParsedMarker] = field(default_factory=list)


async def postprocess(
    inputs: TurnInputs, reply: FinalReply, services: TrpgServices,
) -> PostprocessOutput:
    markers = parse_markers(reply.text)
    state_diff = apply_markers(markers, inputs.session_state)
    side_effects: list[dict[str, Any]] = []

    if inputs.flags.enable_multimedia:
        for marker in markers:
            await _maybe_fire_multimedia(marker, services, side_effects)

    return PostprocessOutput(
        state_diff=state_diff,
        side_effects=side_effects,
        parsed_markers=markers,
    )


async def _maybe_fire_multimedia(
    marker: ParsedMarker,
    services: TrpgServices,
    side_effects: list[dict[str, Any]],
) -> None:
    """Translate one marker into an optional multimedia request. NoOp adapters
    return None, in which case nothing is appended."""
    args = marker.args
    if marker.kind == "create_npc":
        prompt = str(args.get("portrait_prompt") or args.get("appearance") or "")
        npc_key = str(args.get("key") or "")
        if not prompt or not npc_key:
            return
        try:
            ref = await services.multimedia.generate_portrait(
                prompt=prompt, npc_key=npc_key,
            )
        except Exception as exc:  # pragma: no cover - defensive
            side_effects.append({
                "kind": "portrait_error",
                "npc_key": npc_key,
                "error": f"{type(exc).__name__}: {exc}",
            })
            return
        if ref is not None:
            side_effects.append({
                "kind": "portrait", "npc_key": npc_key,
                "url": ref.url, "width": ref.width, "height": ref.height,
            })

    elif marker.kind == "set_scene":
        scene_key = str(args.get("scene") or args.get("to") or "")
        prompt = str(args.get("illustration_prompt") or marker.body or "")
        if not scene_key or not prompt:
            return
        try:
            ref = await services.multimedia.render_scene(
                scene_key=scene_key, prompt=prompt,
            )
        except Exception as exc:  # pragma: no cover - defensive
            side_effects.append({
                "kind": "scene_error",
                "scene_key": scene_key,
                "error": f"{type(exc).__name__}: {exc}",
            })
            return
        if ref is not None:
            side_effects.append({
                "kind": "scene", "scene_key": scene_key,
                "url": ref.url, "width": ref.width, "height": ref.height,
            })
