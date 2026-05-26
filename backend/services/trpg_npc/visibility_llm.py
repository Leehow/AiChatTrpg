"""LLM-augmented player-known-name derivation.

The pure-regex helper in :mod:`services.trpg_npc.visibility` cannot tell
whether an NPC description refers to a person, a creature, or a group —
so when no human-keyword pattern matches, it falls back to the generic
"陌生人" / "unknown person" label. That label is misleading for a
swarm-of-rats or a pile-of-rubble entry the GM dropped into the roster.

This module adds an async post-pass: when the sync regex landed on one
of those generic fallbacks, ask the configured fast model to read the
description and produce a short noun-phrase the player can see in the
sidebar (e.g. "巨鼠群", "灰发司机"). The LLM call is gated, idempotent,
and falls back to a description-truncation when the fast model is
unavailable or returns nothing usable. Once a specific label is on the
NPC dict the helper is a no-op.

Caller pattern (see routes/sessions.py adventure-start and the IC
runner): run the sync ``ensure_npc_visibility_fields`` first to populate
``name_revealed`` + ``player_known_name`` synchronously, then await
``enhance_player_known_names`` on the freshly-touched npc list.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from services import admin_config, model_pool

logger = logging.getLogger("chatrpg.trpg_npc.visibility_llm")


# Labels the sync regex falls back to when it cannot infer anything
# specific. A current ``player_known_name`` matching one of these means
# we should retry with the LLM.
_GENERIC_FALLBACKS = {
    "陌生人",
    "陌生男性",
    "陌生女性",
    "unknown person",
    "unknown man",
    "unknown woman",
}

_DESC_FIELDS = (
    "description",
    "summary",
    "appearance",
    "brief",
    "role",
    "title",
    "portrait_prompt",
)

_PROMPT = (
    "You are labelling a TRPG NPC entry for the player-facing sidebar. "
    "The player has not yet learned this NPC's true name, so the label "
    "must describe what the player observes — never reveal proper "
    "names from the description. Decide what kind of entity it is and "
    "produce a short noun phrase (2 to 8 characters/words) suited to "
    "that kind:\n"
    "- person → appearance + role: '灰发司机', '陌生男人', '红衣女人'\n"
    "- creature / animal → species or descriptor: '巨鼠群', '异形怪物'\n"
    "- group / mob → collective noun: '一伙暴民', '披风修士团'\n"
    "- object / device → what it is: '生锈机器人', '广播喇叭'\n"
    "Match the description's language. Return JSON only: "
    '{"kind": "person|creature|group|object", "label": "<short label>"}'
)


def _provider_default_key(provider: str) -> str:
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _is_generic_fallback(label: str) -> bool:
    return (label or "").strip().lower() in {x.lower() for x in _GENERIC_FALLBACKS}


def _collect_description(npc: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in _DESC_FIELDS:
        value = npc.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip())
    return " ".join(parts)


def _truncate_label(text: str, *, limit: int = 12) -> str:
    """Last-resort fallback when the LLM is unavailable.

    Strip whitespace, take the first clause, hard-cap to ``limit`` chars.
    """
    s = re.sub(r"\s+", "", text or "")
    s = re.split(r"[，。,;；.!?！？]", s, maxsplit=1)[0]
    return s[:limit] if len(s) > limit else s


async def _classify_via_fast(
    db: AsyncSession,
    description: str,
) -> str | None:
    entry = await model_pool.get_fast(db)
    if entry is None:
        return None
    saved = admin_config.get_provider(entry.provider) or {}
    api_key = saved.get("api_key", "") or _provider_default_key(entry.provider)
    base_url = saved.get("base_url", "") or _provider_default_base_url(entry.provider)
    try:
        client = build_client(
            provider=entry.provider,
            model=entry.model,
            api_key=api_key,
            base_url=base_url,
        )
    except (ValueError, TypeError):
        return None
    messages = [
        ChatMessage(role="system", content=_PROMPT),
        ChatMessage(role="user", content=description[:600]),
    ]
    chunks: list[str] = []
    try:
        async for chunk in client.stream_chat(messages, temperature=0.2):
            if chunk.delta:
                chunks.append(chunk.delta)
    except Exception as exc:  # noqa: BLE001 - cosmetic helper, never bubble
        logger.warning("fast-model NPC label call failed: %s", exc)
        return None
    raw = _strip_code_fences("".join(chunks))
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    label = str(payload.get("label") or "").strip()
    return label or None


async def enhance_player_known_name(
    db: AsyncSession,
    npc: dict[str, Any],
) -> bool:
    """Re-derive ``player_known_name`` via the configured fast model
    when the current value is one of the generic stranger fallbacks.

    Idempotent — skips when the name is revealed or the existing label
    is already specific. Returns True when ``npc`` was mutated, so the
    caller can ``flag_modified`` the parent JSON column.
    """
    if not isinstance(npc, dict):
        return False
    if npc.get("name_revealed"):
        return False
    current = str(npc.get("player_known_name") or "").strip()
    if current and not _is_generic_fallback(current):
        return False
    description = _collect_description(npc)
    if not description:
        return False
    label = await _classify_via_fast(db, description)
    if not label:
        label = _truncate_label(description)
    if not label or label == current:
        return False
    npc["player_known_name"] = label
    return True


async def enhance_player_known_names(
    db: AsyncSession,
    npcs: Iterable[dict[str, Any]],
) -> int:
    """Run :func:`enhance_player_known_name` over a list, return the
    count of mutated entries. Caller is responsible for the
    ``flag_modified`` once any change happened.
    """
    touched = 0
    for npc in npcs:
        if await enhance_player_known_name(db, npc):
            touched += 1
    return touched
