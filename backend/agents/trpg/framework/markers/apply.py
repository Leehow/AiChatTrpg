"""Marker → SessionStateDiff translator.

Each marker kind maps to one or more entries on SessionStateDiff. This file
is the canonical place to extend marker semantics — keep parsing in
`parse.py` and effect application here, so a new marker only ever touches
two files.

NPC operations (create / update / set_params / reveal_name) are queued
into ``state_transitions["npc_ops"]`` rather than ``memory_updates`` so the
session-side runner can route them through ``NpcAgent`` and pick up
visibility, psychology, and asset-queue side-effects automatically. The
generic ``MemoryUpdate(bucket="npcs")`` path is intentionally NOT used —
it would create raw NPC dicts without the normaliser passes."""

from __future__ import annotations

import json
import re
from typing import Any

from ..models import (
    MemoryUpdate,
    SceneTransition,
    SessionState,
    SessionStateDiff,
)
from .parse import ParsedMarker


def apply_markers(
    markers: list[ParsedMarker], state: SessionState,
) -> SessionStateDiff:
    """Translate a list of parsed markers into a SessionStateDiff. Caller
    persists the diff. Pure function — no IO, no side effects."""
    diff = SessionStateDiff()
    for m in markers:
        _apply_one(m, state, diff)
    return diff


def _apply_one(
    marker: ParsedMarker, state: SessionState, diff: SessionStateDiff,
) -> None:
    args = marker.args
    body = marker.body
    kind = marker.kind

    if kind == "roll":
        # Record dice consumption. The roll expression and (optional) result
        # come from args; framework just notes that a roll happened, no
        # randomization here — chatlab's dice IR engine handles that
        # separately and may emit its own [ROLL] markers downstream.
        expr = str(args.get("expr") or args.get("dice") or "").strip()
        if expr:
            diff.dice_consumed.append(expr)

    elif kind == "set_scene":
        to_scene = str(args.get("scene") or args.get("to") or body).strip()
        if to_scene:
            mem = state.memory_state if isinstance(state.memory_state, dict) else {}
            from_scene_value = mem.get("current_scene")
            from_scene = (
                str(from_scene_value) if isinstance(from_scene_value, str) else None
            )
            diff.scene_transitions.append(SceneTransition(
                from_scene=from_scene, to_scene=to_scene,
                reason=str(args.get("reason") or ""),
            ))
            diff.memory_updates.append(MemoryUpdate(
                op="merge", bucket="world_facts",
                key="current_scene", value=to_scene,
            ))

    elif kind == "update_memory":
        bucket = _coerce_bucket(args.get("bucket") or args.get("kind"))
        op = _coerce_op(args.get("op"))
        key = args.get("key")
        # Body is the human-readable payload; structured callers can also
        # pass `value=` as an attribute for non-text data.
        value: Any = args.get("value") or body or args.get("text") or ""
        diff.memory_updates.append(MemoryUpdate(
            op=op, bucket=bucket,
            key=str(key) if key else None,
            value=value,
        ))

    elif kind == "create_npc":
        # Body may be either free-form summary text or a JSON blob.
        # JSON wins when it parses, since the GM can pack the full NPC
        # description (motivation, role, voice_hint, etc.) into one block.
        json_payload = _maybe_json_body(body)
        npc_payload: dict[str, Any] = dict(args)
        if json_payload:
            npc_payload.update(json_payload)
        npc_payload.setdefault("key", args.get("key") or args.get("id") or "")
        npc_payload.setdefault("name", args.get("name") or "")
        # Plain text body becomes the summary if no JSON.
        if not json_payload and body:
            npc_payload.setdefault("summary", body.strip())
        _queue_npc_op(diff, {"op": "create", "payload": npc_payload})

    elif kind == "update_npc":
        json_payload = _maybe_json_body(body)
        changes: dict[str, Any] = dict(args)
        if json_payload:
            changes.update(json_payload)
        # Plain text body is treated as a freeform action snippet so the
        # GM can write `[UPDATE_NPC key=vern]Vern draws a knife[/UPDATE_NPC]`
        # without crafting JSON.
        action_text = "" if json_payload else body.strip()
        key = str(
            changes.pop("key", "")
            or changes.pop("id", "")
            or changes.pop("npc_key", "")
        ).strip()
        if key:
            op: dict[str, Any] = {"op": "update", "key": key, "changes": changes}
            if action_text:
                op["action"] = action_text
            _queue_npc_op(diff, op)

    elif kind == "update_npc_params":
        json_payload = _maybe_json_body(body)
        params: dict[str, Any] = {}
        if json_payload and isinstance(json_payload.get("updates"), dict):
            params = dict(json_payload["updates"])
            args_extra = {k: v for k, v in json_payload.items() if k != "updates"}
        else:
            args_extra = json_payload or {}
        # Args take precedence as overrides — `[UPDATE_NPC_PARAMS key=vern hp=8]`
        # is a perfectly valid one-liner.
        for k, v in args.items():
            if k in {"key", "id", "npc_key", "reason"}:
                continue
            params[k] = v
        key = str(
            args.get("key")
            or args.get("id")
            or args.get("npc_key")
            or args_extra.get("key")
            or args_extra.get("npc_key")
            or ""
        ).strip()
        reason = str(args.get("reason") or args_extra.get("reason") or "").strip()
        if key and params:
            _queue_npc_op(diff, {
                "op": "set_params", "key": key, "params": params, "reason": reason,
            })

    elif kind == "reveal_name":
        key = str(args.get("key") or args.get("id") or args.get("npc_key") or "").strip()
        if key:
            _queue_npc_op(diff, {"op": "reveal_name", "key": key})

    elif kind == "update_pc":
        # PC-level field updates flow through state_transitions so the caller
        # can write them onto session.character (or session.characters['pc']).
        pc_diff: dict[str, Any] = {}
        for k, v in args.items():
            pc_diff[k] = v
        if body:
            pc_diff.setdefault("note", body)
        if pc_diff:
            existing = diff.state_transitions.get("pc_update")
            if isinstance(existing, dict):
                existing.update(pc_diff)
            else:
                diff.state_transitions["pc_update"] = pc_diff

    elif kind == "advance_time":
        amount = args.get("by") or args.get("amount") or args.get("minutes")
        if amount is not None:
            diff.memory_updates.append(MemoryUpdate(
                op="merge", bucket="world_facts",
                key="advance_time",
                value={"by": amount, "unit": args.get("unit") or "minutes"},
            ))

    elif kind == "search_module":
        # No state change — caller treats it as a side-effect request.
        # We surface it via state_transitions for traceability.
        existing_q = diff.state_transitions.get("module_searches") or []
        existing_q = list(existing_q) if isinstance(existing_q, list) else []
        existing_q.append({
            "query": str(args.get("q") or args.get("query") or body or "").strip(),
            "limit": args.get("limit"),
        })
        diff.state_transitions["module_searches"] = existing_q

    elif kind in ("create_character", "update_character"):
        # Card-generation flow: payload is JSON in body or value attr.
        card_value: Any = args.get("value") or body
        diff.state_transitions["character_card_update"] = {
            "kind": kind, "value": card_value, "args": dict(args),
        }
        if kind == "create_character":
            diff.state_transitions["character_ready"] = True

    # Unknown kinds are dropped silently; raw_text is still preserved on the
    # ParsedMarker so callers can log them if needed.


def _queue_npc_op(diff: SessionStateDiff, op: dict[str, Any]) -> None:
    """Append an NPC operation to ``state_transitions["npc_ops"]``.

    The runner walks this list (in order) and dispatches each entry to
    ``NpcAgent``. We intentionally don't emit ``MemoryUpdate`` for NPC
    creation because the generic memory writer doesn't run the
    visibility/psychology/asset normalisers."""
    queue = diff.state_transitions.get("npc_ops")
    if not isinstance(queue, list):
        queue = []
    queue.append(op)
    diff.state_transitions["npc_ops"] = queue


_JSON_BODY_RE = re.compile(r"^\s*\{[\s\S]*\}\s*$")


def _maybe_json_body(body: str) -> dict[str, Any] | None:
    """Parse ``body`` as a JSON object if it looks like one, else None.

    The GM is encouraged to pass structured payloads as JSON inside the
    block-form body, but free-form text remains the friendlier fallback
    for one-off updates."""
    if not body or not _JSON_BODY_RE.match(body):
        return None
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_bucket(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s in ("scenes", "npcs", "plot_threads", "world_facts", "narrative"):
        return s
    # Default to world_facts — least surprising place for orphan memory bits.
    return "world_facts"


def _coerce_op(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s in ("append", "replace", "delete", "merge"):
        return s
    return "append"
