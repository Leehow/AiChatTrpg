"""Prompt-safe NPC projection.

The existing ``prompt_safe_active_npcs`` test already checks that ``name`` and
``secret_agenda`` are not leaked.  This module makes that guarantee stronger by
using a whitelist projection instead of a blacklist deletion pass.

Use this module before any NPC data is injected into the main scene prompt.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable, Mapping

from services.trpg_npc.visibility import mask_hidden_true_name

from .common import first_non_empty, get_value, stable_list, to_plain_data

# Keys that should never appear in player-facing or main-scene prompt payloads.
PRIVATE_KEY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"secret",
        r"private",
        r"forbidden",
        r"core_?secret",
        r"gm_?notes?",
        r"true_?goal",
        r"hidden",
        r"plot_?constraints?",
        r"knowledge_?fact_?ids?",
        r"forbidden_?fact_?ids?",
        r"raw_?prompt",
        r"raw_?response",
        r"system_?prompt",
        r"api_?key",
        r"authorization",
        r"password",
        r"token",
    ]
]

PUBLIC_PLAYER_KNOWLEDGE_KEYS = {
    "interest",
    "relationship",
    "public_relationship",
    "known_as",
    "last_interaction_summary",
    "visible_attitude",
}

PUBLIC_INNER_STATE_KEYS = {
    "emotional_state",
    "visible_behavior",
    "visible_mood",
    "surface_mood",
    "apparent_intent",
    "stress_visible",
}

PUBLIC_RUNTIME_STATE_KEYS = {
    "current_mode",
    "status",
}

PUBLIC_MOOD_KEYS = {
    "valence",
    "arousal",
    "fear",
    "anger",
    "curiosity",
    "suspicion",
    "stress",
    "fatigue",
}


def _matches_private_key(key: str) -> bool:
    return any(pattern.search(key) for pattern in PRIVATE_KEY_PATTERNS)


def _safe_display_name(npc: Any) -> str:
    """Return a display name without revealing a hidden real name."""

    player_known_name = get_value(npc, "player_known_name")
    public_name = get_value(npc, "public_name")
    display_name = get_value(npc, "display_name")
    name_revealed = bool(get_value(npc, "name_revealed", False))
    name = get_value(npc, "name")
    role = get_value(npc, "role") or get_value(npc, "narrative_role") or "NPC"
    npc_id = get_value(npc, "key") or get_value(npc, "npc_id") or get_value(npc, "id")

    if player_known_name:
        return str(player_known_name)
    if public_name:
        return str(public_name)
    if display_name:
        return str(display_name)
    if name_revealed and name:
        return str(name)
    if role and role != "NPC":
        return f"未透露姓名的{role}"
    if npc_id:
        return f"未透露姓名的NPC({npc_id})"
    return "未透露姓名的NPC"


def _safe_dict_subset(data: Any, allowed_keys: Iterable[str]) -> dict[str, Any]:
    plain = to_plain_data(data) or {}
    if not isinstance(plain, Mapping):
        return {}
    allowed = set(allowed_keys)
    result: dict[str, Any] = {}
    for key, value in plain.items():
        if key in allowed and not _matches_private_key(key):
            if isinstance(value, (dict, list)):
                # Nested state is frequently where secrets leak.  Keep simple scalars only
                # unless the caller has explicitly whitelisted a nested projection elsewhere.
                continue
            result[str(key)] = value
    return result


def _looks_private_text(text: str) -> bool:
    lowered = (text or "").lower()
    markers = [
        "secret",
        "true identity",
        "real goal",
        "hidden",
        "forbidden",
        "gm note",
        "keeper note",
        "秘密",
        "真实身份",
        "真正目标",
        "隐藏",
        "幕后",
        "主谋",
        "核心秘密",
        "邪教首领",
        "最终反派",
    ]
    return any(marker in lowered for marker in markers)


def _public_summary(npc: Any) -> str | None:
    for value in [
        get_value(npc, "public_summary"),
        get_value(npc, "player_visible_summary"),
        get_value(npc, "appearance"),
        get_value(npc, "public_description"),
    ]:
        if value:
            return str(value)

    summary = get_value(npc, "summary")
    if summary and not _looks_private_text(str(summary)):
        return str(summary)
    return None


def prompt_safe_active_npcs_hardened(active_npcs: list[Any]) -> list[dict[str, Any]]:
    """Build a whitelist-only projection of active NPCs for prompts.

    The output intentionally does *not* include raw ``name``, ``inner_state``,
    ``runtime_state_v2``, ``relationships_v2``, ``memories_v2`` or any other
    private structure.  If a new private field is added to the project, it will
    not leak unless this function explicitly whitelists it.
    """

    safe_npcs: list[dict[str, Any]] = []
    for npc in active_npcs or []:
        # Mask the true name *on a copy* so downstream projection sees the
        # public label in the `name` field when `name_revealed=False`. The
        # caller's session memory keeps the real name intact — only this
        # wire-payload copy is mutated. Mirrors chatlab's
        # `_mask_hidden_true_name`, which made the rule a data invariant
        # after empirically confirming that prompt-only "don't use the name"
        # instructions did not survive a few turns of LLM drift.
        masked = deepcopy(npc) if isinstance(npc, dict) else npc
        if isinstance(masked, dict):
            mask_hidden_true_name(masked)

        npc_id = first_non_empty(
            get_value(masked, "key"),
            get_value(masked, "npc_id"),
            get_value(masked, "id"),
            default="unknown_npc",
        )
        display_name = _safe_display_name(masked)
        # Expose `name` (already masked above when name_revealed=False) so the
        # GM has the same conceptual handle ChatLab uses, plus `name_revealed`
        # so the prompt can branch on it. `display_name` is kept as the
        # always-safe public label.
        public: dict[str, Any] = {
            "key": str(npc_id),
            "name": str(get_value(masked, "name") or display_name),
            "display_name": display_name,
            "name_revealed": bool(get_value(masked, "name_revealed", False)),
        }

        for source_key, out_key in [
            ("role", "role"),
            ("narrative_role", "narrative_role"),
            ("last_seen_scene", "last_seen_scene"),
            ("location_id", "location_id"),
        ]:
            value = get_value(npc, source_key)
            if value not in (None, "", [], {}):
                public[out_key] = value

        summary = _public_summary(npc)
        if summary:
            public["summary"] = str(summary)[:800]

        player_knowledge = _safe_dict_subset(
            get_value(npc, "player_knowledge"),
            PUBLIC_PLAYER_KNOWLEDGE_KEYS,
        )
        if player_knowledge:
            public["player_knowledge"] = player_knowledge

        inner_state = _safe_dict_subset(
            get_value(npc, "inner_state"),
            PUBLIC_INNER_STATE_KEYS,
        )
        if inner_state:
            public["inner_state"] = inner_state

        runtime_state = get_value(npc, "runtime_state_v2") or {}
        runtime_public = _safe_dict_subset(runtime_state, PUBLIC_RUNTIME_STATE_KEYS)
        mood = get_value(runtime_state, "mood", {}) if runtime_state else {}
        mood_public = _safe_dict_subset(mood, PUBLIC_MOOD_KEYS)
        if mood_public:
            # Mood values are allowed only as coarse public behavior hints.  Keep the
            # numeric state compact to avoid giving the scene LLM too much private state.
            runtime_public["mood_hint"] = mood_public
        if runtime_public:
            public["runtime_hint"] = runtime_public

        # Optional public facts must be explicitly stored under player_known_facts.
        facts = stable_list(get_value(npc, "player_known_facts"))
        if facts:
            public["player_known_facts"] = [str(f)[:300] for f in facts[:8]]

        safe_npcs.append(public)
    return safe_npcs


def scan_prompt_safety_violations(payload: Any, path: str = "$", max_text_scan: int = 5000) -> list[str]:
    """Return human-readable paths that look unsafe for prompt injection.

    This is meant for tests and diagnostics.  It scans keys recursively and also
    looks for obviously private markers in string values.
    """

    violations: list[str] = []
    plain = to_plain_data(payload)

    def walk(value: Any, current_path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_str = str(key)
                child_path = f"{current_path}.{key_str}"
                if _matches_private_key(key_str):
                    violations.append(child_path)
                walk(child, child_path)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{current_path}[{idx}]")
        elif isinstance(value, str):
            text = value[:max_text_scan]
            lowered = text.lower()
            for marker in ["secret_agenda", "core secret", "gm note", "forbidden_fact"]:
                if marker in lowered:
                    violations.append(current_path)
                    break

    walk(plain, path)
    return violations
