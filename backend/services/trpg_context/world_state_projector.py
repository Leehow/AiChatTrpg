"""Field-level world-state projection for prompt construction.

ContextBlock visibility protects whole blocks. World-state objects are often
mixed objects, so callers must project them per actor before placing them in a
block.
"""

from __future__ import annotations

from typing import Any, Mapping

from .models import ActorScope, ContextProfile, Visibility

_SECRET_KEY_HINTS = ("gm_secret", "secret", "keeper_only", "spoiler", "hidden_truth")


def project_world_state(world_state: Mapping[str, Any], *, actor: ActorScope) -> dict[str, Any]:
    return _project_value(world_state, actor=actor, parent_visibility=None)


def _project_value(value: Any, *, actor: ActorScope, parent_visibility: Visibility | None) -> Any:
    if isinstance(value, Mapping):
        explicit = _parse_visibility(value.get("visibility")) if "visibility" in value else None
        effective = explicit or parent_visibility
        if effective is not None and not _can_read_visibility(effective, actor, owner_id=_owner_id(value)):
            return None
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if key_s in {"visibility", "owner_id"}:
                continue
            if _is_secret_key(key_s) and actor.profile != ContextProfile.GM:
                continue
            projected = _project_value(item, actor=actor, parent_visibility=effective)
            if projected is not None:
                out[key_s] = projected
        return out
    if isinstance(value, list):
        out_list = []
        for item in value:
            projected = _project_value(item, actor=actor, parent_visibility=parent_visibility)
            if projected is not None:
                out_list.append(projected)
        return out_list
    return value


def _parse_visibility(value: Any) -> Visibility | None:
    if isinstance(value, Visibility):
        return value
    if isinstance(value, str):
        try:
            return Visibility(value)
        except ValueError:
            return None
    return None


def _owner_id(value: Mapping[str, Any]) -> str | None:
    owner = value.get("owner_id")
    return str(owner) if owner else None


def _can_read_visibility(visibility: Visibility, actor: ActorScope, *, owner_id: str | None) -> bool:
    if actor.profile == ContextProfile.GM:
        return True
    if actor.profile == ContextProfile.PLAYER:
        return visibility in {Visibility.PUBLIC, Visibility.PARTY_KNOWN}
    if actor.profile == ContextProfile.NPC:
        return visibility == Visibility.PUBLIC or (visibility == Visibility.NPC_PRIVATE and owner_id == actor.npc_id)
    if actor.profile == ContextProfile.MEMORY_EXTRACTOR:
        return visibility in {Visibility.PUBLIC, Visibility.PARTY_KNOWN, Visibility.GM_ONLY, Visibility.SYSTEM_INTERNAL}
    if actor.profile == ContextProfile.RULE_ADJUDICATOR:
        return visibility in {Visibility.PUBLIC, Visibility.PARTY_KNOWN}
    return False


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("_") or any(hint in lowered for hint in _SECRET_KEY_HINTS)
