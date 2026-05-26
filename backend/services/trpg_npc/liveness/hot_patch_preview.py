"""Foreground-only hot patch previews.

Hot patches are meant to affect the current turn immediately, without waiting
for post-turn state persistence. The preview copy is used by behavior policy and
optional hot planning, while the real commit still happens after the visible
reply.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .common import clamp, get_value, set_value, to_plain_data


def apply_hot_patches_preview(states_by_id: dict[str, Any], patches: Iterable[Any]) -> dict[str, Any]:
    effective = {npc_id: deepcopy(state) for npc_id, state in (states_by_id or {}).items()}
    for patch in patches or []:
        npc_id = str(get_value(patch, "npc_id") or get_value(patch, "target_id") or "")
        if not npc_id or npc_id not in effective:
            continue
        effective[npc_id] = apply_hot_patch_preview(effective[npc_id], patch)
    return effective


def apply_hot_patch_preview(state: Any, patch: Any) -> Any:
    preview = deepcopy(state)
    patch_data = to_plain_data(patch) or {}
    if not isinstance(patch_data, dict):
        return preview

    mood_delta = _first_dict(
        patch_data.get("mood_delta"),
        patch_data.get("temporary_mood_delta"),
        patch_data.get("mood"),
    )
    goal_delta = _first_dict(
        patch_data.get("goal_pressure_delta"),
        patch_data.get("temporary_goal_pressure_delta"),
        patch_data.get("goal_pressure"),
    )
    flags = _first_dict(patch_data.get("active_flags"), patch_data.get("flags"))

    _apply_numeric_delta(preview, "mood", mood_delta)
    _apply_numeric_delta(preview, "goal_pressure", goal_delta)

    if flags:
        existing_flags = get_value(preview, "active_flags") or {}
        if not isinstance(existing_flags, dict):
            existing_flags = {}
        existing_flags = dict(existing_flags)
        existing_flags.update(flags)
        set_value(preview, "active_flags", existing_flags)

    return preview


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _apply_numeric_delta(obj: Any, bucket_name: str, delta: dict[str, Any]) -> None:
    if not delta:
        return
    bucket = get_value(obj, bucket_name)
    if bucket is None:
        bucket = {}
        set_value(obj, bucket_name, bucket)
    for key, amount in delta.items():
        current = get_value(bucket, key, 0.0)
        new_value = clamp(float(current or 0.0) + float(amount or 0.0))
        set_value(bucket, key, new_value)
