"""IC runtime state-diff helpers.

Extracted from `services.trpg_ic_runner` to keep that orchestrator near the
project's 400-line soft target. Behavior, signatures, ORM mutation semantics,
NPC memory ops, dice-history writes, and the marker-driven scene-name
recovery in `_apply_state_diff` are unchanged — the runner re-exports these
names so existing call sites keep working.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from agents.trpg.check_spec_registry import build_runtime_check_spec
from agents.trpg.framework.models import SessionStateDiff
from orm.models import GameSession, Ruleset

logger = logging.getLogger("chatrpg.trpg")


# ---------------------------------------------------------------------------
# Runtime helpers


def _runtime_check_spec_for_ruleset(ruleset: Ruleset) -> dict[str, Any]:
    """Build the runtime dice-resolution spec used by inline markers.

    Chatlab stores a helper on session; chatrpg has the applied spec on the
    Ruleset row. Adding the ruleset name lets the CoC runtime coerce generic
    compiled specs to the deterministic d100 engine when appropriate.
    """
    return build_runtime_check_spec(ruleset)


def _memory_npcs(session: GameSession) -> list[dict[str, Any]]:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return []
    return [npc for npc in npcs if isinstance(npc, dict)]


# ---------------------------------------------------------------------------
# State diff persistence


def _ensure_memory_buckets(mem: dict[str, Any]) -> dict[str, Any]:
    for key in ("scenes", "npcs", "plot_threads", "world_facts"):
        mem.setdefault(key, [])
    return mem


def _apply_state_diff(
    session: GameSession,
    diff: SessionStateDiff,
    *,
    parsed_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mutate the ORM row to reflect the framework's diff. Pure-ish: only
    touches `session.memory_state`, `session.module_state`, `session.dice_history`,
    `session.character` (for pc_update). Returns a small summary for the UI.

    `parsed_markers` (optional) carries the raw marker dicts so we can pick
    up the human-readable scene display name from a `[SET_SCENE ...]Body[/SET_SCENE]`
    marker (the framework's `SceneTransition` only carries the snake_case
    key, not the display name)."""
    mem = (
        dict(session.memory_state)
        if isinstance(session.memory_state, dict) else {}
    )
    _ensure_memory_buckets(mem)

    for upd in diff.memory_updates:
        bucket = upd.bucket
        if bucket == "narrative":
            mem.setdefault("narrative", "")
            if upd.op == "replace":
                mem["narrative"] = str(upd.value or "")
            else:
                existing = str(mem.get("narrative") or "")
                addition = str(upd.value or "")
                mem["narrative"] = (
                    f"{existing}\n{addition}".strip() if existing else addition
                )
            continue

        if bucket == "npcs":
            # `npcs` is a list of NPC dicts keyed by `.key`, not a dict-keyed
            # bucket. The generic merge/replace branches below would coerce
            # the list into a dict (or wipe it entirely), corrupting the
            # roster that NpcAgent + scene runtime rely on. Route through
            # the NpcAgent-aware helper so the schema stays intact.
            _apply_npc_memory_update(session, mem, upd)
            continue

        existing = mem.get(bucket)
        if upd.op == "append":
            if not isinstance(existing, list):
                existing = []
            existing.append(upd.value)
            mem[bucket] = existing
        elif upd.op == "replace":
            mem[bucket] = upd.value
        elif upd.op == "merge":
            if upd.key:
                # store as dict-of-{key: value} so subsequent merges accumulate
                if not isinstance(existing, dict):
                    existing = {}
                existing[str(upd.key)] = upd.value
                mem[bucket] = existing
            elif isinstance(existing, dict) and isinstance(upd.value, dict):
                existing.update(upd.value)
                mem[bucket] = existing
            else:
                mem[bucket] = upd.value
        elif upd.op == "delete":
            if upd.key and isinstance(existing, dict):
                existing.pop(str(upd.key), None)
                mem[bucket] = existing

    if diff.scene_transitions:
        last = diff.scene_transitions[-1]
        ms = (
            dict(session.module_state)
            if isinstance(session.module_state, dict) else {}
        )
        ms["scene"] = last.to_scene
        if last.reason:
            ms["scene_reason"] = last.reason
        # Pull scene display name from the most recent matching set_scene
        # marker's body (e.g. `[SET_SCENE scene=highway]Devil's Backbone[/SET_SCENE]`
        # → scene_name="Devil's Backbone"). Falls back to the snake_case key.
        display_name = ""
        for m in reversed(parsed_markers or []):
            if m.get("kind") == "set_scene":
                body = str(m.get("body") or "").strip()
                args = m.get("args") or {}
                key_match = (
                    str(args.get("scene") or args.get("to") or "").strip()
                    == last.to_scene
                )
                if body and (key_match or not display_name):
                    display_name = body
                    if key_match:
                        break
        if display_name:
            ms["scene_name"] = display_name
        elif "scene_name" in ms and ms.get("scene") != ms.get("scene_name_for"):
            # Stale name carried over from a previous scene — clear it.
            ms.pop("scene_name", None)
        ms["scene_name_for"] = last.to_scene
        session.module_state = ms

    if diff.dice_consumed:
        history = list(session.dice_history or [])
        for expr in diff.dice_consumed:
            history.append({
                "expression": expr,
                "result": None,
                "time": datetime.now(timezone.utc).isoformat(),
                "source": "marker",
            })
        session.dice_history = history

    pc_update = diff.state_transitions.get("pc_update")
    if isinstance(pc_update, dict) and pc_update:
        char = (
            dict(session.character)
            if isinstance(session.character, dict) else {}
        )
        char.update(pc_update)
        session.character = char

    # NPC operations from `[CREATE_NPC]` / `[UPDATE_NPC]` / `[UPDATE_NPC_PARAMS]`
    # / `[REVEAL_NAME]` markers. The framework apply layer queues these into
    # state_transitions["npc_ops"] so we can dispatch through NpcAgent — that
    # way every creation picks up visibility + psychology + asset queueing,
    # and every update goes through the same dirty-tracking + flag_modified
    # path as the rest of the agent. Must run AFTER the generic memory
    # writes above (which already set `session.memory_state = mem`), so the
    # agent reads the freshest list state.
    session.memory_state = mem
    npc_ops = diff.state_transitions.get("npc_ops")
    npc_ops_summary = _apply_npc_ops(session, npc_ops if isinstance(npc_ops, list) else [])

    # JSON columns: SQLAlchemy doesn't track in-place mutation of nested
    # lists/dicts, and a same-reference reassignment may also be ignored. Mark
    # explicitly so the change actually persists on commit.
    flag_modified(session, "memory_state")
    if diff.scene_transitions:
        flag_modified(session, "module_state")
    if diff.dice_consumed:
        flag_modified(session, "dice_history")
    if isinstance(pc_update, dict) and pc_update:
        flag_modified(session, "character")
    return {
        "memory_updates": len(diff.memory_updates),
        "dice_consumed": len(diff.dice_consumed),
        "scene_transitions": len(diff.scene_transitions),
        "pc_updated": bool(pc_update),
        "npc_ops": npc_ops_summary,
    }


def _apply_npc_memory_update(
    session: GameSession,
    mem: dict[str, Any],
    upd: Any,
) -> None:
    """Translate a `[UPDATE_MEMORY bucket=npcs ...]` write into something
    the NPC roster (a list of NPC dicts) can actually accept.

    The framework parses `[UPDATE_MEMORY]` generically, so a careless GM
    `bucket=npcs op=merge key=X` would otherwise hit the dict-merge branch
    in `_apply_state_diff` and CORRUPT the roster (replace the list with a
    `{key: value}` dict). This helper preserves the list shape and routes
    through NpcAgent — which knows the schema, visibility flags, and
    psychology re-derivation.

    Recognised shapes:
      - ``op=merge key=<npc_key>``: dict body merges fields onto the
        matching NPC; string body appends to ``actions[]`` (treated as a
        free-form fact about the NPC). Unknown keys → silent no-op
        (avoid spawning stub roster entries).
      - ``op=append``: a dict body becomes a roster entry via
        NpcAgent.add (skip-if-exists); other shapes → no-op.
      - ``op=replace`` / ``op=delete``: refused. Marker semantics on
        npcs would have to wipe the list — too dangerous.
    """
    npcs_bucket = mem.get("npcs")
    if not isinstance(npcs_bucket, list):
        npcs_bucket = []
        mem["npcs"] = npcs_bucket

    op = str(getattr(upd, "op", "") or "").strip().lower()
    key = str(getattr(upd, "key", "") or "").strip()
    value = getattr(upd, "value", None)

    # The shape we want to preserve: list of {"key": ..., ...} dicts.
    from services.trpg_npc import NpcAgent
    # Apply through a temporary session view bound to `mem` so the agent
    # mutates the same list reference we will write back at the end.
    session.memory_state = mem
    agent = NpcAgent(session)

    if op == "merge" and key:
        target = agent.get(key)
        if target is None:
            logger.info(
                "[chatrpg.ic] [UPDATE_MEMORY bucket=npcs key=%s] skipped — NPC not in roster",
                key,
            )
            return
        if isinstance(value, dict):
            agent.update(key, **value)
            return
        # Non-dict body (typically a one-line natural-language fact).
        # Append it to the action history so NPC-aware prompts pick it up
        # without overwriting structured fields.
        text = str(value or "").strip()
        if text:
            agent.append_actions(key, [text])
        return

    if op == "append":
        if isinstance(value, dict) and value.get("key"):
            agent.add(value, default_revealed=False, skip_if_exists=True)
        else:
            logger.info(
                "[chatrpg.ic] [UPDATE_MEMORY bucket=npcs op=append] skipped — value is not a roster entry dict",
            )
        return

    # replace / delete / unrecognised: refuse, never re-shape the list.
    logger.warning(
        "[chatrpg.ic] [UPDATE_MEMORY bucket=npcs op=%s] refused — use a dedicated NPC marker instead",
        op or "?",
    )


def _apply_npc_ops(
    session: GameSession,
    ops: list[Any],
) -> dict[str, int]:
    """Dispatch each marker-emitted NPC op through NpcAgent.

    Skips malformed entries silently — markers are meant to be best-effort.
    Returns op counts for the route summary.
    """
    summary = {"create": 0, "update": 0, "set_params": 0, "reveal_name": 0, "skipped": 0}
    if not ops:
        return summary
    from services.trpg_npc import NpcAgent

    agent = NpcAgent(session)
    current_scene = ""
    if isinstance(session.memory_state, dict):
        current_scene = str(session.memory_state.get("current_scene") or "").strip()

    for op in ops:
        if not isinstance(op, dict):
            summary["skipped"] += 1
            continue
        kind = str(op.get("op") or "").strip()
        if kind == "create":
            payload = op.get("payload") if isinstance(op.get("payload"), dict) else {}
            added = agent.add(payload, default_revealed=False)
            if added is not None:
                if current_scene:
                    agent.mark_seen(added.get("key", ""), current_scene)
                summary["create"] += 1
            else:
                summary["skipped"] += 1
        elif kind == "update":
            key = str(op.get("key") or "").strip()
            changes = op.get("changes") if isinstance(op.get("changes"), dict) else {}
            if not key:
                summary["skipped"] += 1
                continue
            updated = agent.update(key, **changes) if changes else agent.get(key)
            if updated is None:
                summary["skipped"] += 1
                continue
            action_text = str(op.get("action") or "").strip()
            if action_text:
                agent.append_actions(key, [action_text])
            if current_scene:
                agent.mark_seen(key, current_scene)
            summary["update"] += 1
        elif kind == "set_params":
            key = str(op.get("key") or "").strip()
            params = op.get("params") if isinstance(op.get("params"), dict) else {}
            reason = str(op.get("reason") or "").strip()
            if not key or not params:
                summary["skipped"] += 1
                continue
            target = agent.get(key)
            if target is None:
                summary["skipped"] += 1
                continue
            existing_params = target.get("params") if isinstance(target.get("params"), dict) else {}
            merged = dict(existing_params)
            for pkey, pval in params.items():
                if "." in str(pkey):
                    parts = str(pkey).split(".")
                    cursor: Any = merged
                    for part in parts[:-1]:
                        next_node = cursor.get(part)
                        if not isinstance(next_node, dict):
                            next_node = {}
                            cursor[part] = next_node
                        cursor = next_node
                    cursor[parts[-1]] = pval
                else:
                    merged[pkey] = pval
            agent.update(key, params=merged)
            if reason:
                agent.update(key, params_update_reason=reason)
            summary["set_params"] += 1
        elif kind == "reveal_name":
            key = str(op.get("key") or "").strip()
            if not key:
                summary["skipped"] += 1
                continue
            if agent.reveal_name(key):
                summary["reveal_name"] += 1
            else:
                summary["skipped"] += 1
        else:
            summary["skipped"] += 1

    if agent.is_dirty():
        # Don't await save() here — the surrounding _apply_state_diff has its
        # own flag_modified at the end and the caller commits the transaction.
        # Just leave the in-memory mutations on `session`.
        pass
    return summary


__all__ = [
    "_runtime_check_spec_for_ruleset",
    "_memory_npcs",
    "_ensure_memory_buckets",
    "_apply_state_diff",
    "_apply_npc_memory_update",
    "_apply_npc_ops",
]
