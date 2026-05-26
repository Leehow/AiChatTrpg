"""Actor/character lookup adapter for runtime CHECK requests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .check_resolver import CheckArgs


@dataclass
class ActorLookupContext:
    pc: dict[str, Any] = field(default_factory=dict)
    npcs: list[dict[str, Any]] = field(default_factory=list)


_PC_ALIASES = {"pc", "player", "character", "investigator", "玩家", "主角", "角色"}
_NAME_FIELDS = (
    "key", "id", "npc_id", "name", "display_name", "player_known_name",
    "public_name", "role",
)
_VALUE_FIELDS = (
    "value", "current", "full", "base", "rating", "score", "total",
    "starting", "max", "maximum",
)
_SECTION_FIELDS = (
    "params", "skills", "attributes", "characteristics", "derived",
    "derived_values", "resources", "stats", "abilities",
)
_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "spot hidden": ("侦查",),
    "spot_hidden": ("侦查",),
    "listen": ("聆听",),
    "stealth": ("潜行",),
    "dodge": ("闪避",),
    "brawl": ("近战", "格斗"),
    "fighting": ("近战", "格斗"),
    "firearms": ("射击",),
    "psychology": ("心理学",),
    "persuade": ("说服",),
    "fast talk": ("话术",),
    "charm": ("取悦",),
    "intimidate": ("恐吓",),
    "library use": ("图书馆使用",),
    "first aid": ("急救",),
    "medicine": ("医学",),
    "sanity": ("理智", "SAN"),
    "luck": ("幸运", "LUCK", "FATE"),
}


def build_actor_lookup_context(session: Any) -> ActorLookupContext:
    pc = getattr(session, "character", None)
    mem = getattr(session, "memory_state", None)
    npcs = mem.get("npcs") if isinstance(mem, dict) else []
    return ActorLookupContext(
        pc=pc if isinstance(pc, dict) else {},
        npcs=[npc for npc in npcs if isinstance(npc, dict)]
        if isinstance(npcs, list) else [],
    )


def apply_actor_value_lookup(
    args: CheckArgs,
    context: ActorLookupContext | Mapping[str, Any] | None,
) -> CheckArgs:
    """Fill ``args.value`` from PC/NPC data when marker only names actor+skill."""

    if context is None:
        return args
    extras = dict(args.extras or {})
    actor = _first_text(
        extras.get("actor"),
        extras.get("actor_id"),
        extras.get("npc_key"),
    )
    check_key = _first_text(
        extras.get("check"),
        extras.get("check_key"),
        extras.get("param"),
        args.skill,
    )
    if not actor or not check_key:
        args.extras = extras
        return args
    source_name, actor_data = _resolve_actor(actor, context)
    if actor_data is None:
        _append_warning(extras, f"actor lookup failed: unknown actor {actor!r}")
        extras["actor_lookup"] = {
            "actor": actor,
            "check": check_key,
            "found": False,
            "reason": "actor_not_found",
        }
        args.extras = extras
        return args

    if args.value not in (None, ""):
        extras["actor_lookup"] = {
            "actor": actor,
            "source": source_name,
            "check": check_key,
            "found": True,
            "used_marker_value": True,
            "value": args.value,
        }
        args.extras = extras
        return args

    value, matched_path = _lookup_numeric(actor_data, check_key)
    if value is None:
        _append_warning(
            extras,
            f"actor lookup failed: {source_name}.{check_key} has no numeric value",
        )
        extras["actor_lookup"] = {
            "actor": actor,
            "source": source_name,
            "check": check_key,
            "found": False,
            "reason": "value_not_found",
        }
        args.extras = extras
        return args

    args.value = value
    extras["actor_lookup"] = {
        "actor": actor,
        "source": source_name,
        "check": check_key,
        "found": True,
        "path": matched_path,
        "value": value,
    }
    args.extras = extras
    return args


def has_actor_lookup_request(args: CheckArgs) -> bool:
    extras = args.extras or {}
    return bool(
        _first_text(extras.get("actor"), extras.get("actor_id"), extras.get("npc_key"))
        and _first_text(extras.get("check"), extras.get("check_key"), extras.get("param"), args.skill)
    )


def _resolve_actor(
    actor: str,
    context: ActorLookupContext | Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    pc, npcs = _context_parts(context)
    norm = _norm(actor)
    if norm in {_norm(a) for a in _PC_ALIASES}:
        return "pc", pc or None
    if norm.startswith("npc:"):
        norm = norm[4:]
    for npc in npcs:
        for field in _NAME_FIELDS:
            raw = npc.get(field)
            if raw not in (None, "") and _norm(raw) == norm:
                return f"npc:{npc.get('key') or npc.get('id') or raw}", npc
    return f"actor:{actor}", None


def _context_parts(
    context: ActorLookupContext | Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(context, ActorLookupContext):
        return context.pc, context.npcs
    pc = context.get("pc") if isinstance(context.get("pc"), dict) else {}
    raw_npcs = context.get("npcs")
    npcs = [npc for npc in raw_npcs if isinstance(npc, dict)] if isinstance(raw_npcs, list) else []
    return pc, npcs


def _lookup_numeric(actor_data: Mapping[str, Any], key: str) -> tuple[int | float | None, str]:
    aliases = _aliases(key)
    value, path = _lookup_in_value(actor_data, aliases, path="")
    if value is not None:
        return value, path
    for section in _SECTION_FIELDS:
        child = actor_data.get(section)
        value, path = _lookup_in_value(child, aliases, path=section)
        if value is not None:
            return value, path
    return None, ""


def _lookup_in_value(value: Any, aliases: set[str], *, path: str) -> tuple[int | float | None, str]:
    direct = _extract_number(value)
    if direct is not None and path:
        return direct, path
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _norm(key) in aliases:
                number = _extract_number(child)
                if number is not None:
                    return number, _join_path(path, str(key))
            if _norm(key) in aliases and isinstance(child, (Mapping, list)):
                number, child_path = _lookup_in_value(child, aliases, path=_join_path(path, str(key)))
                if number is not None:
                    return number, child_path
        for key, child in value.items():
            if str(key) in _SECTION_FIELDS:
                number, child_path = _lookup_in_value(child, aliases, path=_join_path(path, str(key)))
                if number is not None:
                    return number, child_path
    if isinstance(value, list):
        for idx, item in enumerate(value):
            if not isinstance(item, Mapping):
                continue
            item_names = [
                item.get("name"), item.get("key"), item.get("id"),
                item.get("label"), item.get("skill"), item.get("param"),
            ]
            if any(_norm(name) in aliases for name in item_names if name not in (None, "")):
                number = _extract_number(item)
                if number is not None:
                    return number, _join_path(path, str(idx))
    return None, ""


def _extract_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
        return None
    if isinstance(value, Mapping):
        for field in _VALUE_FIELDS:
            if field in value:
                number = _extract_number(value.get(field))
                if number is not None:
                    return number
    return None


def _aliases(key: str) -> set[str]:
    out = {_norm(key)}
    raw = str(key or "").strip()
    for alias in _SKILL_ALIASES.get(raw.lower(), ()):
        out.add(_norm(alias))
    for source, aliases in _SKILL_ALIASES.items():
        if _norm(raw) in {_norm(a) for a in aliases}:
            out.add(_norm(source))
            out.update(_norm(a) for a in aliases)
    return {item for item in out if item}


def _append_warning(extras: dict[str, Any], warning: str) -> None:
    warnings = extras.get("check_warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(warning)
    extras["check_warnings"] = warnings


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _join_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _norm(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())
