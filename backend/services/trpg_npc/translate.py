"""Lazy on-demand NPC field translation.

Mirrors ``services/character_translator.py`` for the NPC roster:
when the player switches the global language, this batch-translates
each NPC's narrative fields (``name`` / ``player_known_name`` /
``role`` / ``description`` / ``summary`` / ``motivation`` /
``personality`` / ``appearance`` / ``voice_hint`` / ``dialogue_style``)
into the target language. Numeric values, params, IDs, voice IDs,
portrait URLs, and visibility flags are left untouched.

One LLM call per session — every NPC in ``memory_state.npcs[]`` goes in
the same batch. Output is normalised back onto the existing dicts so
keys / params / portrait_url survive.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.llm_json import call_llm_json_task


logger = logging.getLogger("chatrpg.trpg_npc.translate")


_TRANSLATABLE_FIELDS = (
    "name",
    "player_known_name",
    "role",
    "title",
    "description",
    "summary",
    "appearance",
    "personality",
    "motivation",
    "secret_agenda",
    "voice_hint",
    "dialogue_style",
)


_LANGUAGE_NAMES: dict[str, str] = {
    "zh": "Simplified Chinese",
    "zh_cn": "Simplified Chinese",
    "zh-cn": "Simplified Chinese",
    "zh_hant": "Traditional Chinese",
    "zh-hant": "Traditional Chinese",
    "en": "English",
    "en_us": "English",
    "en-us": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "ru": "Russian",
    "pt": "Portuguese",
}


SYSTEM_PROMPT = """You translate TRPG NPC roster entries into {language}.

You will receive a JSON object whose values are NPC dicts keyed by
their stable ``key``. Each NPC has any subset of these fields:
``name`` / ``player_known_name`` / ``role`` / ``title`` /
``description`` / ``summary`` / ``appearance`` / ``personality`` /
``motivation`` / ``secret_agenda`` / ``voice_hint`` / ``dialogue_style``.

Rules:
- Translate ONLY the fields present in the input. Don't invent fields.
- Personal names: render in the target language using natural transliteration
  (e.g. "Karen Xu" → "凯伦·徐" for Simplified Chinese; "马洛" → "Marlowe"
  for English). Keep the cultural register.
- Descriptions / motivations / etc.: idiomatic prose in the target
  language, preserve meaning, keep similar length.
- ``player_known_name`` is the player-facing label when the NPC's true
  name is hidden ("瘦长皮卡司机", "doctor", etc.). Translate it as a
  natural label in the target language; do NOT promote it to a real name.
- Skip any field that is already in the target language.
- Return STRICT JSON only, no markdown fences, no commentary. The output
  must be a JSON object whose keys match the input keys exactly.
- Each output entry contains only the translated fields; omit fields you
  did not touch.
"""


async def translate_session_npcs(
    db: AsyncSession,
    npcs: list[dict[str, Any]],
    *,
    target_language: str,
) -> int:
    """Translate every NPC's narrative fields in place.

    Returns the number of NPCs that received at least one updated
    field. Mutates the passed list directly; caller commits + flags
    ``memory_state``.
    """
    if not isinstance(npcs, list) or not npcs:
        return 0

    from routes.rulesets import _resolve_default_compiler_config

    cfg = await _resolve_default_compiler_config(db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise RuntimeError(
            "No API config available for the default compiler model",
        )

    language = _normalise_language(target_language)
    payload: dict[str, dict[str, str]] = {}
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = str(npc.get("key") or "").strip()
        if not key:
            continue
        entry: dict[str, str] = {}
        for field in _TRANSLATABLE_FIELDS:
            value = npc.get(field)
            if isinstance(value, str) and value.strip():
                entry[field] = value
        if entry:
            payload[key] = entry

    if not payload:
        return 0

    user_msg = (
        f"Translate the following NPC fields to {language}. Return "
        f"JSON only.\n\n```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```"
    )

    try:
        raw = await call_llm_json_task(
            stage="npc_translate",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            system_prefix=SYSTEM_PROMPT.replace("{language}", language),
            user_message=user_msg,
            stream=False,
        )
    except Exception:
        logger.warning(
            "[chatrpg.trpg_npc.translate] LLM call failed", exc_info=True,
        )
        raise

    translated = _parse_translation_response(raw)
    if not translated:
        return 0

    npc_index = {
        str(n.get("key") or ""): n
        for n in npcs
        if isinstance(n, dict) and n.get("key")
    }
    changed_count = 0
    for key, fields in translated.items():
        npc = npc_index.get(str(key))
        if npc is None or not isinstance(fields, dict):
            continue
        npc_changed = False
        for field, new_value in fields.items():
            if field not in _TRANSLATABLE_FIELDS:
                continue
            text = str(new_value or "").strip()
            if not text:
                continue
            if str(npc.get(field) or "") == text:
                continue
            npc[field] = text
            npc_changed = True
        if npc_changed:
            changed_count += 1
    return changed_count


def _parse_translation_response(raw: str) -> dict[str, Any]:
    body = (raw or "").strip()
    if body.startswith("```"):
        # Strip fenced code blocks if the model added them despite our prompt.
        import re as _re
        body = _re.sub(r"^```[a-zA-Z0-9]*\s*", "", body)
        body = _re.sub(r"\s*```$", "", body).strip()
    if not body:
        return {}
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(body)
    except json.JSONDecodeError:
        start = body.find("{")
        if start < 0:
            return {}
        try:
            obj, _end = decoder.raw_decode(body[start:])
        except json.JSONDecodeError:
            logger.warning(
                "[chatrpg.trpg_npc.translate] could not parse JSON: %.200s",
                body,
            )
            return {}
    if not isinstance(obj, dict):
        return {}
    # Some models wrap the result under a top-level "translations" key (matching
    # the chatlab prompt). Accept either shape.
    if "translations" in obj and isinstance(obj["translations"], dict):
        return obj["translations"]
    return obj


def _normalise_language(value: str) -> str:
    raw = (value or "").strip()
    lower = raw.lower().replace("_", "-")
    if lower in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[lower]
    if lower in {"zh", "zh-cn"}:
        return "Simplified Chinese"
    if not raw:
        return "Simplified Chinese"
    # If the caller already passed a full language name (e.g. "Simplified
    # Chinese", "English") just use that.
    return raw
