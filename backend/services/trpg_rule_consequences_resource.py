"""Resource/actor lookup helpers for rule-consequence application.

These helpers are shared infrastructure for the rule-consequence engine:
- Locate the actor JSON root on a ``GameSession`` (PC ``character`` or an NPC
  entry inside ``memory_state``).
- Apply numeric deltas to dotted resource paths with clamping and SQLAlchemy
  JSON-mutation flagging.
- Small numeric / collection primitives used across the engine.

Nothing in this module knows about CheckExecution or sanity rules; that lives
in sibling modules.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified


def apply_resource_delta(
    session: Any,
    actor_id: str,
    *,
    resource: str,
    delta: int | float,
    before_hint: Any = None,
    path_candidates: list[str] | tuple[str, ...] | None = None,
    clamp_min: Any = None,
) -> dict[str, Any]:
    target, dirty_attr = actor_root(session, actor_id)
    if target is None:
        return {
            "resource": resource,
            "delta": delta,
            "before": before_hint,
            "after": None,
            "path": "",
            "applied": False,
            "reason": "actor_not_found",
        }

    candidates = list(path_candidates or generic_resource_paths(resource))
    existing_path = first_existing_numeric_path(target, candidates)
    path = existing_path or canonical_resource_path(resource)
    before = number(get_dot(target, path)) if existing_path else number(before_hint)
    if before is None:
        return {
            "resource": resource,
            "delta": delta,
            "before": None,
            "after": None,
            "path": path,
            "applied": False,
            "reason": "missing_before_value",
        }
    after = before + float(delta)
    min_value = number(clamp_min)
    if min_value is not None:
        after = max(min_value, after)
    if float(after).is_integer():
        after = int(after)
    set_dot(target, path, after)
    safe_flag_modified(session, dirty_attr)
    return {
        "resource": resource,
        "delta": int(delta) if float(delta).is_integer() else delta,
        "before": int(before) if float(before).is_integer() else before,
        "after": after,
        "path": path,
        "applied": True,
    }


def actor_root(session: Any, actor_id: str) -> tuple[dict[str, Any] | None, str]:
    actor = str(actor_id or "pc").strip()
    if not actor or actor.lower() in {"pc", "player", "character", "玩家", "主角", "角色"}:
        char = getattr(session, "character", None)
        if not isinstance(char, dict):
            char = {}
            session.character = char
        return char, "character"

    mem = getattr(session, "memory_state", None)
    if not isinstance(mem, dict):
        return None, "memory_state"
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return None, "memory_state"
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if actor in {
            str(npc.get("key") or ""),
            str(npc.get("id") or ""),
            str(npc.get("npc_id") or ""),
            str(npc.get("name") or ""),
            str(npc.get("player_known_name") or ""),
            str(npc.get("public_name") or ""),
        }:
            return npc, "memory_state"
    return None, "memory_state"


def lookup_named_numeric(root: Any, key: str) -> float | None:
    if isinstance(root, dict):
        if key in root:
            value = number(root.get(key))
            if value is not None:
                return value
            if isinstance(root.get(key), dict):
                value = first_numeric_in_dict(root[key])
                if value is not None:
                    return value
        lowered = key.lower()
        for raw_key, raw_value in root.items():
            if str(raw_key).lower() == lowered:
                value = number(raw_value)
                if value is not None:
                    return value
                if isinstance(raw_value, dict):
                    value = first_numeric_in_dict(raw_value)
                    if value is not None:
                        return value
            found = lookup_named_numeric(raw_value, key)
            if found is not None:
                return found
    if isinstance(root, list):
        for item in root:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("key") or item.get("id") or "")
                if name.lower() == key.lower():
                    value = first_numeric_in_dict(item)
                    if value is not None:
                        return value
            found = lookup_named_numeric(item, key)
            if found is not None:
                return found
    return None


def first_numeric_in_dict(raw: dict[str, Any]) -> float | None:
    for key in ("value", "current", "full", "base", "score", "total", "rating"):
        value = number(raw.get(key))
        if value is not None:
            return value
    return None


def generic_resource_paths(resource: str) -> list[str]:
    name = safe_resource_name(resource)
    return [
        f"resources.{name}.current",
        f"{name}.current",
        f"params.resources.{name}.current",
        f"params.{name}.current",
    ]


def canonical_resource_path(resource: str) -> str:
    return f"resources.{safe_resource_name(resource)}.current"


def safe_resource_name(resource: str) -> str:
    text = str(resource or "resource").strip().lower()
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in text) or "resource"


def first_existing_numeric_path(root: dict[str, Any], paths: list[str]) -> str:
    for path in paths:
        if number(get_dot(root, path)) is not None:
            return path
    return ""


def get_dot(root: dict[str, Any], path: str) -> Any:
    current: Any = root
    for part in str(path or "").split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_dot(root: dict[str, Any], path: str, value: Any) -> None:
    parts = [p for p in str(path or "").split(".") if p]
    if not parts:
        return
    current = root
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def number(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def string_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item or "").strip()]
    return []


def system_id_from_procedure(procedure_id: str) -> str:
    text = str(procedure_id or "")
    return text.split(".", 1)[0] if "." in text else ""


def dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def safe_flag_modified(obj: Any, attr: str) -> None:
    try:
        flag_modified(obj, attr)
    except Exception:
        pass
