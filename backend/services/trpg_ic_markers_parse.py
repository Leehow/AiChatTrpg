"""Body extractors for chatrpg-extension IC markers.

Split out of ``trpg_ic_markers.py`` for file-size budget. These are the
pure-parse helpers consumed by ``parse_chatrpg_markers`` — they convert
the inner text of one marker into a typed Python value (dict, string,
or mutation on the shared ``IcMarkerExtraction``). No SQLAlchemy, no
session state.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.trpg_ic_markers import IcMarkerExtraction


_ATTR_RE = re.compile(
    r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
    r'(?:"(?P<qval>[^"]*)"|'
    r"'(?P<sval>[^']*)'|"
    r'(?P<bval>[^\s\]"]+))'
)


def _try_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _parse_take_time_into(body: str, out: "IcMarkerExtraction") -> None:
    raw = body.lower()

    # Explicit target clock has highest priority for narrative coherence.
    clock_m = re.search(r"\b(\d{1,2})\s*[:点]\s*(\d{1,2})?", raw)
    if clock_m:
        hour = int(clock_m.group(1))
        minute = int(clock_m.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.target_clock = f"{hour:02d}:{minute:02d}"

    # "3 days" / "2 day" → time leap
    leap_m = re.match(r"(\d+)\s*days?", raw)
    if leap_m:
        out.time_leap_days = int(leap_m.group(1))
        return

    # Sleep / overnight / day-end keywords → next morning
    if re.search(
        r"next\s*morning|day[\s_]end|overnight|night\s*rest|sleep|睡|过夜|次日|第二天",
        raw,
    ):
        out.day_ended = True
        return

    # NdMm: hours/minutes accumulator. e.g. "1h20min", "2h", "30min", "45m"
    hours = 0
    minutes = 0
    h_m = re.search(r"(\d+)\s*(?:h|小时|hr)", raw)
    if h_m:
        hours = int(h_m.group(1))
    min_m = re.search(r"(\d+)\s*(?:min|m\b|分钟|分)", raw)
    if min_m:
        minutes = int(min_m.group(1))
    total = hours * 60 + minutes
    if total > 0:
        out.elapsed_minutes = total


def _extract_objective(body: str) -> str | None:
    """Pull `objective` from JSON body or, failing that, treat the whole body
    as the objective text."""
    body = body.strip()
    if not body:
        return None
    parsed = _try_json(body)
    if isinstance(parsed, dict):
        text = parsed.get("objective") or parsed.get("text") or parsed.get("goal")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return body[:300]


def _extract_note(body: str) -> dict[str, Any] | None:
    parsed = _try_json(body.strip())
    content = ""
    tags: list[str] = []
    if isinstance(parsed, dict):
        content = str(parsed.get("content") or parsed.get("text") or "").strip()
        raw_tags = parsed.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    else:
        content = body.strip()
    if not content:
        return None
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "tags": tags,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_npc_param_update(body: str) -> dict[str, Any] | None:
    """Pull `{npc_key, updates, reason}` from a JSON body. Drops malformed
    entries silently — the GM may emit a stub the player should not see."""
    parsed = _try_json(body.strip())
    if not isinstance(parsed, dict):
        return None
    npc_key = str(parsed.get("npc_key") or parsed.get("key") or "").strip()
    updates = parsed.get("updates")
    if not npc_key or not isinstance(updates, dict) or not updates:
        return None
    reason = str(parsed.get("reason") or "").strip()
    return {"npc_key": npc_key, "updates": updates, "reason": reason}


def _extract_search_rules(*, attrs_text: str, body: str) -> dict[str, Any] | None:
    """Pull `query` / `package_id` / `family_id` / `entry` out of a
    `[SEARCH_RULES ...]` marker. Returns None when nothing usable was given.

    The block form lets the GM put a free-text query as the body
    (`[SEARCH_RULES]vampires and werewolves[/SEARCH_RULES]`); attrs win when
    both are present."""
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attrs_text or ""):
        key = m.group("key").lower()
        val = m.group("qval") if m.group("qval") is not None else (
            m.group("sval") if m.group("sval") is not None else m.group("bval") or ""
        )
        attrs[key] = val
    query = (attrs.get("query") or body or "").strip()
    pid = (attrs.get("package_id") or attrs.get("package") or "").strip() or None
    fid = (attrs.get("family_id") or attrs.get("family") or "").strip() or None
    entry = (attrs.get("entry") or attrs.get("name") or "").strip() or None
    if not (query or pid or fid or entry):
        return None
    return {"query": query, "package_id": pid, "family_id": fid, "entry": entry}


def _extract_name_reveal(*, attrs_text: str, body: str) -> dict[str, Any] | None:
    """Parse one `[name_reveal npc_key="..." name="..."]` marker.

    ``npc_key`` is required — it identifies which roster entry to flip.
    ``name`` is the now-revealed true name (also written into
    ``player_known_name`` on flip). Body text becomes ``reason`` for
    debug surfaces. Returns ``None`` when ``npc_key`` is missing.
    """
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attrs_text or ""):
        key = (m.group("key") or "").lower()
        val = m.group("qval") or m.group("sval") or m.group("bval") or ""
        attrs[key] = val.strip()
    npc_key = attrs.get("npc_key") or attrs.get("key") or ""
    npc_key = npc_key.strip()
    if not npc_key:
        return None
    name = (attrs.get("name") or attrs.get("true_name") or "").strip()
    reason = str(body or "").strip()
    return {"npc_key": npc_key, "name": name, "reason": reason[:240]}


def _extract_pc_param_update(body: str) -> dict[str, Any] | None:
    parsed = _try_json(body.strip())
    if not isinstance(parsed, dict):
        return None
    updates = parsed.get("updates")
    if not isinstance(updates, dict) or not updates:
        return None
    reason = str(parsed.get("reason") or "").strip()
    return {"updates": updates, "reason": reason}
