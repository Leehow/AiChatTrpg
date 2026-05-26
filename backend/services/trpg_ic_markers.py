"""chatrpg-specific IC marker extensions (path B: outside the framework).

The portable framework parses 9 marker kinds (roll / set_scene / update_memory
/ create_npc / update_pc / advance_time / search_module / create_character /
update_character). Anything else is dropped silently.

This module adds chatlab-style markers chatrpg cares about, without polluting
the shared framework:

  [TAKE_TIME]30min[/TAKE_TIME]              — accumulate in-game time
  [SET_OBJECTIVE]{...}[/SET_OBJECTIVE]      — internal narrative-beat tracker
  [ADD_NOTE]{...}[/ADD_NOTE]                — player notebook entry
  [UPDATE_NPC_PARAMS]{...}[/...]            — write NPC HP/composure/etc
  [UPDATE_PC_PARAMS]{...}[/...]             — write PC HP/SAN/QA/etc

`parse_chatrpg_markers(text)` extracts them; `apply_chatrpg_markers(session,
extraction, gm_message_metadata)` applies the side-effects:

  module_state.elapsed_minutes / in_game_time / day_count / objective
  memory_state.player_notes[]
  memory_state.npcs[i].params[...]          (dot-path keys e.g. "hp.current")
  session.character[...]                    (dot-path keys e.g. "qualities.duplicity.current_qa")
  gm_message_metadata.objective / notes / npc_param_updates / pc_param_update

Time semantics adapted from chatlab `time_tracker.parse_take_time_marker`
but without the timeline/compression machinery (those land in wave 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_ic_markers_parse import (
    _extract_name_reveal,
    _extract_note,
    _extract_npc_param_update,
    _extract_objective,
    _extract_pc_param_update,
    _extract_search_rules,
    _parse_take_time_into,
)


_TAKE_TIME_RE = re.compile(
    r"\[TAKE_?TIME\](.*?)\[/TAKE_?TIME\]", re.IGNORECASE | re.DOTALL,
)
_SET_OBJECTIVE_RE = re.compile(
    r"\[SET_?OBJECTIVE\](.*?)\[/SET_?OBJECTIVE\]", re.IGNORECASE | re.DOTALL,
)
_ADD_NOTE_RE = re.compile(
    r"\[ADD_?NOTE\](.*?)\[/ADD_?NOTE\]", re.IGNORECASE | re.DOTALL,
)
_UPDATE_NPC_PARAMS_RE = re.compile(
    r"\[UPDATE_?NPC_?PARAMS\](.*?)\[/UPDATE_?NPC_?PARAMS\]",
    re.IGNORECASE | re.DOTALL,
)
_UPDATE_PC_PARAMS_RE = re.compile(
    r"\[UPDATE_?PC_?PARAMS\](.*?)\[/UPDATE_?PC_?PARAMS\]",
    re.IGNORECASE | re.DOTALL,
)
# `[SEARCH_RULES query="..."]` / `[SEARCH_RULES package_id="combat"]` /
# `[SEARCH_RULES family_id="weapon" entry="Knife, Small"]` — both
# self-closing (no body) and block-form (`[SEARCH_RULES]<query>[/SEARCH_RULES]`)
# are tolerated. Attributes share the same `key="value"` shape as
# `[CHECK]`, so we lean on `_ATTR_RE` here.
_SEARCH_RULES_OPEN_RE = re.compile(
    r"\[SEARCH_?RULES\b([^\]]*)\]", re.IGNORECASE,
)
_SEARCH_RULES_BLOCK_RE = re.compile(
    r"\[SEARCH_?RULES\b([^\]]*)\](.*?)\[/SEARCH_?RULES\]",
    re.IGNORECASE | re.DOTALL,
)
# `[name_reveal npc_key="..." name="..."][/name_reveal]` — visible reveal
# chip + flips the matching NPC's `name_revealed=true` server-side. Open
# form (no body) and block form (optional context line in body) are both
# tolerated; the body, if present, is surfaced as `reason` for debug.
_NAME_REVEAL_BLOCK_RE = re.compile(
    r"\[name_reveal\b([^\]]*)\](.*?)\[/name_reveal\]",
    re.IGNORECASE | re.DOTALL,
)
_NAME_REVEAL_OPEN_RE = re.compile(
    r"\[name_reveal\b([^\]]*)\](?!\s*\[/name_reveal\])",
    re.IGNORECASE,
)


@dataclass
class IcMarkerExtraction:
    """All chatrpg-extension marker effects extracted from one GM reply."""

    elapsed_minutes: int = 0
    day_ended: bool = False
    time_leap_days: int = 0
    target_clock: str | None = None
    raw_take_time: str | None = None
    objective: str | None = None
    notes: list[dict[str, Any]] = field(default_factory=list)
    # NPC param edits: each entry is {"npc_key": "...", "updates": {dot.path: value}, "reason": "..."}
    npc_param_updates: list[dict[str, Any]] = field(default_factory=list)
    # `[SEARCH_RULES ...]` requests. The actual lookup happens in
    # `stream_ic_turn` (needs db + ruleset row) and the result is persisted
    # as a `role=system` message so the GM sees it next turn.
    search_rules_queries: list[dict[str, Any]] = field(default_factory=list)
    # PC param edit: at most one merged dict {"updates": {...}, "reason": "..."} per turn
    pc_param_update: dict[str, Any] | None = None
    # `[name_reveal]` events: each {"npc_key": "...", "name": "...",
    # "reason": "..."}. Drives the visible chip on the GM message *and*
    # flips `name_revealed=true` on the matching roster entry.
    name_reveals: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            self.elapsed_minutes == 0
            and not self.day_ended
            and self.time_leap_days == 0
            and self.target_clock is None
            and self.objective is None
            and not self.notes
            and not self.npc_param_updates
            and not self.search_rules_queries
            and self.pc_param_update is None
            and not self.name_reveals
        )


# ---------------------------------------------------------------------------
# parse


def parse_chatrpg_markers(text: str) -> IcMarkerExtraction:
    """Extract chatrpg-extension markers from a raw GM reply.

    Returns an empty extraction if none are present. Tolerates bracket
    casing variations (`TAKE_TIME` / `taketime` / `Take_Time`) and accepts
    JSON or plain-text bodies; on JSON parse failure the body is treated
    as the human-readable value where that makes sense (objective)."""
    out = IcMarkerExtraction()
    if not text:
        return out

    take_time = _TAKE_TIME_RE.search(text)
    if take_time:
        body = take_time.group(1).strip()
        out.raw_take_time = body
        _parse_take_time_into(body, out)

    objective = _SET_OBJECTIVE_RE.search(text)
    if objective:
        out.objective = _extract_objective(objective.group(1))

    for m in _ADD_NOTE_RE.finditer(text):
        note = _extract_note(m.group(1))
        if note is not None:
            out.notes.append(note)

    for m in _UPDATE_NPC_PARAMS_RE.finditer(text):
        entry = _extract_npc_param_update(m.group(1))
        if entry is not None:
            out.npc_param_updates.append(entry)

    pc_param = _UPDATE_PC_PARAMS_RE.search(text)
    if pc_param:
        out.pc_param_update = _extract_pc_param_update(pc_param.group(1))

    # `[SEARCH_RULES ...]` requests. The block form accepts a free-text body
    # as the implicit query; the self-closing form relies entirely on attrs.
    seen_search_spans: set[tuple[int, int]] = set()
    for m in _SEARCH_RULES_BLOCK_RE.finditer(text):
        entry = _extract_search_rules(attrs_text=m.group(1), body=m.group(2))
        if entry is not None:
            out.search_rules_queries.append(entry)
        seen_search_spans.add(m.span())
    for m in _SEARCH_RULES_OPEN_RE.finditer(text):
        if any(m.start() >= s and m.end() <= e for s, e in seen_search_spans):
            continue  # already captured by the block matcher
        entry = _extract_search_rules(attrs_text=m.group(1), body="")
        if entry is not None:
            out.search_rules_queries.append(entry)

    # `[name_reveal npc_key="..." name="..."]` — visible reveal chip +
    # state flip. Block form lets the GM tuck a one-line reason into the
    # body for debug ("the door tag read 'R. Russell'"); open form is
    # the common case and carries everything in the attrs.
    seen_reveal_spans: set[tuple[int, int]] = set()
    for m in _NAME_REVEAL_BLOCK_RE.finditer(text):
        entry = _extract_name_reveal(attrs_text=m.group(1), body=m.group(2))
        if entry is not None:
            out.name_reveals.append(entry)
        seen_reveal_spans.add(m.span())
    for m in _NAME_REVEAL_OPEN_RE.finditer(text):
        if any(m.start() >= s and m.end() <= e for s, e in seen_reveal_spans):
            continue
        entry = _extract_name_reveal(attrs_text=m.group(1), body="")
        if entry is not None:
            out.name_reveals.append(entry)

    return out


def _set_dot_path(target: dict[str, Any], path: str, value: Any) -> None:
    """Mutate `target` so that `path` (e.g. `hp.current`) ends up at `value`.

    Creates intermediate dicts as needed. If a non-dict is encountered partway
    through (e.g. previous turn stored `hp` as an int), it is replaced with a
    fresh dict so the dotted update lands cleanly. Top-level paths just set
    the bare key."""
    parts = [p for p in str(path or "").split(".") if p]
    if not parts:
        return
    cursor: Any = target
    for key in parts[:-1]:
        nxt = cursor.get(key) if isinstance(cursor, dict) else None
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


# ---------------------------------------------------------------------------
# apply


# Reasonable default chunks when GM only wrote a fuzzy time hint.
_NEXT_MORNING_HOUR = 7
_OVERNIGHT_HOURS = 8


def _clock_to_minutes(clock: Any) -> int | None:
    text = str(clock or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _clock_from_minutes(total_minutes: int) -> str:
    minute_of_day = int(total_minutes) % (24 * 60)
    hour, minute = divmod(minute_of_day, 60)
    return f"{hour:02d}:{minute:02d}"


def _period_key_from_clock(clock: str) -> str:
    minute = _clock_to_minutes(clock)
    if minute is None:
        return ""
    hour = minute // 60
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _set_clock_fields(module_state: dict[str, Any], clock: str) -> None:
    module_state["in_game_time"] = clock
    period = _period_key_from_clock(clock)
    if period:
        module_state["in_game_period"] = period


def apply_chatrpg_markers(
    session: GameSession,
    extraction: IcMarkerExtraction,
    *,
    gm_message_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Apply extension-marker effects onto session ORM fields, and stash
    per-turn artifacts (objective, notes) onto the message metadata so the
    UI can render them inline.

    Returns a small summary dict for the SSE Done payload."""
    if extraction.is_empty():
        return {}

    summary: dict[str, Any] = {}
    module_state = (
        dict(session.module_state)
        if isinstance(session.module_state, dict) else {}
    )

    # ----- TAKE_TIME → module_state.elapsed_minutes / day_count / in_game_time
    minutes_added = 0
    if extraction.day_ended:
        minutes_added += _OVERNIGHT_HOURS * 60
    if extraction.time_leap_days > 0:
        minutes_added += extraction.time_leap_days * 24 * 60
    minutes_added += extraction.elapsed_minutes

    if minutes_added > 0 or extraction.target_clock or extraction.day_ended:
        prev = int(module_state.get("elapsed_minutes") or 0)
        module_state["elapsed_minutes"] = prev + minutes_added
        day_count = int(module_state.get("day_count") or 1)
        module_state["day_count"] = day_count
        if extraction.day_ended:
            module_state["day_count"] = day_count + max(1, extraction.time_leap_days)
            _set_clock_fields(module_state, f"{_NEXT_MORNING_HOUR:02d}:00")
        elif extraction.time_leap_days:
            module_state["day_count"] = day_count + extraction.time_leap_days
        if extraction.target_clock:
            _set_clock_fields(module_state, extraction.target_clock)
        elif minutes_added > 0 and not extraction.day_ended:
            base_minutes = _clock_to_minutes(module_state.get("in_game_time"))
            if base_minutes is None:
                # Older freeform sessions may have accumulated elapsed time
                # without an initialized clock. Treat 09:00 as the implicit
                # session start and include previously stored elapsed minutes.
                base_minutes = 9 * 60 + prev
            total_clock_minutes = base_minutes + minutes_added
            day_overflow, _ = divmod(total_clock_minutes, 24 * 60)
            if day_overflow:
                module_state["day_count"] = int(module_state.get("day_count") or 1) + day_overflow
            _set_clock_fields(module_state, _clock_from_minutes(total_clock_minutes))
        summary["elapsed_minutes_added"] = minutes_added
        if extraction.day_ended:
            summary["day_ended"] = True
        if extraction.target_clock:
            summary["target_clock"] = extraction.target_clock
        gm_message_metadata.setdefault("take_time", {
            "added_minutes": minutes_added,
            "day_ended": extraction.day_ended,
            "target_clock": extraction.target_clock,
            "raw": extraction.raw_take_time,
        })

    # ----- SET_OBJECTIVE → module_state.objective (replace each turn)
    if extraction.objective is not None:
        prev_obj = module_state.get("objective")
        module_state["objective"] = extraction.objective
        gm_message_metadata.setdefault("objective", extraction.objective)
        summary["objective_changed"] = (prev_obj != extraction.objective)

    if (
        minutes_added > 0
        or extraction.target_clock
        or extraction.day_ended
        or extraction.objective is not None
    ):
        session.module_state = module_state
        flag_modified(session, "module_state")

    # ----- ADD_NOTE → memory_state.player_notes[]
    # ----- UPDATE_NPC_PARAMS → memory_state.npcs[i].params (dot-path)
    needs_memory_flag = False
    memory_state: dict[str, Any] | None = None
    if extraction.notes or extraction.npc_param_updates:
        memory_state = (
            dict(session.memory_state)
            if isinstance(session.memory_state, dict) else {}
        )

    if extraction.notes and memory_state is not None:
        notes_bucket = memory_state.get("player_notes")
        if not isinstance(notes_bucket, list):
            notes_bucket = []
        notes_bucket.extend(extraction.notes)
        memory_state["player_notes"] = notes_bucket
        gm_message_metadata.setdefault(
            "added_notes", [n["content"] for n in extraction.notes],
        )
        summary["notes_added"] = len(extraction.notes)
        needs_memory_flag = True

    if extraction.npc_param_updates and memory_state is not None:
        npcs_bucket = memory_state.get("npcs")
        if not isinstance(npcs_bucket, list):
            npcs_bucket = []
        # index NPCs by key once so multiple updates this turn touching the
        # same NPC all land on the same dict (no list-position confusion).
        idx = {
            str(n.get("key") or "").strip(): n
            for n in npcs_bucket if isinstance(n, dict)
        }
        applied: list[dict[str, Any]] = []
        for entry in extraction.npc_param_updates:
            key = entry["npc_key"]
            target = idx.get(key)
            if target is None:
                applied.append({"npc_key": key, "status": "npc_not_found"})
                continue
            params = target.get("params")
            if not isinstance(params, dict):
                params = {}
            for path, value in entry["updates"].items():
                _set_dot_path(params, str(path), value)
            target["params"] = params
            applied.append({
                "npc_key": key,
                "status": "updated",
                "updates": dict(entry["updates"]),
                "reason": entry.get("reason") or "",
            })
        memory_state["npcs"] = npcs_bucket
        gm_message_metadata.setdefault("npc_param_updates", applied)
        summary["npc_param_updates"] = sum(
            1 for a in applied if a.get("status") == "updated"
        )
        needs_memory_flag = True

    # ----- name_reveal → flip name_revealed=true via NpcAgent
    if extraction.name_reveals:
        from services.trpg_npc import NpcAgent
        agent = NpcAgent(session)
        applied_reveals: list[dict[str, Any]] = []
        for entry in extraction.name_reveals:
            npc_key = str(entry.get("npc_key") or "").strip()
            if not npc_key:
                continue
            flipped = bool(agent.reveal_name(npc_key))
            applied_reveals.append({
                "npc_key": npc_key,
                "name": entry.get("name") or "",
                "reason": entry.get("reason") or "",
                "flipped": flipped,  # False if already revealed (idempotent)
            })
        if applied_reveals:
            gm_message_metadata.setdefault("name_reveals", applied_reveals)
            summary["name_reveals"] = sum(
                1 for r in applied_reveals if r.get("flipped")
            )
            if agent.is_dirty():
                # The agent writes through to session.memory_state; flag
                # modified so SQLAlchemy commits the JSON column change.
                memory_state = (
                    dict(session.memory_state)
                    if isinstance(session.memory_state, dict) else None
                )
                needs_memory_flag = True

    if memory_state is not None:
        session.memory_state = memory_state
        if needs_memory_flag:
            flag_modified(session, "memory_state")
    elif extraction.name_reveals and needs_memory_flag:
        # Reveal-only path: agent mutated memory_state in place via the
        # NpcAgent ref. Flag-modify directly without rebuilding the dict.
        flag_modified(session, "memory_state")

    # ----- UPDATE_PC_PARAMS → session.character (dot-path)
    if extraction.pc_param_update is not None:
        char = (
            dict(session.character)
            if isinstance(session.character, dict) else {}
        )
        for path, value in extraction.pc_param_update["updates"].items():
            _set_dot_path(char, str(path), value)
        session.character = char
        flag_modified(session, "character")
        gm_message_metadata.setdefault("pc_param_update", {
            "updates": dict(extraction.pc_param_update["updates"]),
            "reason": extraction.pc_param_update.get("reason") or "",
        })
        summary["pc_param_update"] = True

    return summary
