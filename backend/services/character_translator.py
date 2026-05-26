"""Translate a session's character JSON values to a target language.

The character_ui compiler only translates the LAYOUT (section titles +
field labels). The character data itself — skill names, weapon names,
equipment names, descriptions — comes from the character generator,
which keeps whatever language the GM produced. This service runs a
one-shot LLM translation pass over the character JSON so the in-sidebar
display matches the user's chosen language end-to-end.

Numeric values, dice expressions, IDs, and universal attribute codes
(STR/CON/DEX/...) are preserved verbatim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.llm_json import call_llm_json_task


SYSTEM_PROMPT = """You are translating a TRPG character sheet JSON to {language}.

Translate ONLY the human-visible string values: skill names, weapon
names, equipment / item names, occupation labels, location names,
description / notes / backstory paragraphs, condition labels, etc.

Do NOT translate:
- Numeric values, percentages, dice expressions (1D6, +1D4, 1d100, etc.)
- Top-level schema keys (`identity`, `attributes`, `skills`,
  `equipment`, …)
- Universal attribute abbreviations: STR, CON, SIZ, DEX, APP, INT,
  POW, EDU, LUCK, CHA, WIS, SAN — keep these as-is everywhere
  including object keys, since they're recognised across CoC / BRP
  localisations.
- IDs, slugs, schema_version, template_version, book_id, etc.
- Any value already in the target language.

Personal-name display rule:
- Preserve original/canonical-name fields such as `original_name`,
  `identity.original_name`, `native_name`, and `canonical_name` verbatim.
- For player-facing primary name fields (`name`, `display_name`,
  `character_name`, `identity.name`, `identity.display_name`, etc.), render
  the name as a natural phonetic form in {language}, followed by the original
  in square brackets when the original is from another language/script:
  `phonetic rendering[Original Name]`.
- If the name is already naturally readable in {language}, keep it as-is.

Preserve the JSON shape EXACTLY. Translate string values in-place.
Keep arrays as arrays, objects as objects. Don't drop fields.

Return ONLY the translated JSON object — no surrounding prose, no
markdown fences.
"""


# Map a free-form language hint (BCP-47 tag, English name, native script,
# etc.) to a verbose language name the LLM understands. New languages: add
# a row here AND a matching entry in
# `frontend/src/lib/character_languages.SUPPORTED_LANGUAGES`. The LLM will
# happily translate to anything in this table.
_LANGUAGE_NAMES: dict[str, str] = {
    "zh": "Chinese (simplified)",
    "zh-cn": "Chinese (simplified)",
    "zh-hans": "Chinese (simplified)",
    "chinese": "Chinese (simplified)",
    "中文": "Chinese (simplified)",
    "zh-tw": "Chinese (traditional)",
    "zh-hant": "Chinese (traditional)",
    "繁體中文": "Chinese (traditional)",
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "japanese": "Japanese",
    "日本語": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "한국어": "Korean",
    "fr": "French",
    "french": "French",
    "français": "French",
    "de": "German",
    "german": "German",
    "deutsch": "German",
    "es": "Spanish",
    "spanish": "Spanish",
    "español": "Spanish",
    "it": "Italian",
    "italian": "Italian",
    "ru": "Russian",
    "russian": "Russian",
    "русский": "Russian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
}


def _normalise_language(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[s]
    # Fallback: pass the raw string through if it looks like a language
    # name (alphabetic + few tokens). The LLM is robust to this — if it
    # can't translate, it'll just leave the JSON unchanged.
    if s and len(s) <= 60:
        return raw.strip()
    return "English"


def _strip_fence(text: str) -> str:
    body = (text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    return body.strip()


async def translate_character(
    db: AsyncSession,
    character: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    """Run one LLM pass to translate the character JSON. Returns the new
    object; caller persists. Raises on transport failure or unparseable
    output.
    """
    if not isinstance(character, dict) or not character:
        raise ValueError("character is empty")

    # Imported lazily so this service has no runtime dep on routes.
    from routes.rulesets import _resolve_default_compiler_config

    cfg = await _resolve_default_compiler_config(db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise RuntimeError(
            "No API config available for the default compiler model",
        )

    language = _normalise_language(target_language)
    system_prompt = SYSTEM_PROMPT.replace("{language}", language)
    user_msg = (
        f"Translate this character to {language}. Return only the "
        f"resulting JSON object.\n\n```json\n"
        + json.dumps(character, ensure_ascii=False, indent=2)
        + "\n```"
    )

    raw = await call_llm_json_task(
        stage="character_translate",
        model=cfg["model"],
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        system_prefix=system_prompt,
        user_message=user_msg,
        stream=False,
    )

    body = _strip_fence(raw)
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(body)
    except json.JSONDecodeError as exc:
        # Fall back to greedy slice to recover from a stray leading char.
        start = body.find("{")
        if start < 0:
            raise ValueError(f"translator returned non-JSON: {exc}") from exc
        obj, _end = decoder.raw_decode(body[start:])

    if not isinstance(obj, dict):
        raise ValueError(
            f"translator returned non-object: {type(obj).__name__}",
        )
    return obj
