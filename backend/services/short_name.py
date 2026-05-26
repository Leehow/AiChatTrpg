"""Generate short ASCII tags for rulesets and clean titles for modules.

Both helpers route through the model pool's "fast" entry — cheap, low
latency, used for cosmetic naming. Results are cached on the owning row
so repeated requests don't keep hitting the LLM. Both fall back to a
heuristic if no fast model is configured or the call fails, so the
naming always produces *something* the UI can render.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from orm.models import ParsedModule, Ruleset
from services import admin_config, model_pool

logger = logging.getLogger("chatrpg.short_name")

_RULESET_PROMPT = (
    "You are a tabletop RPG system identifier. Given a rulebook title and "
    "an optional snippet of its content, return a short ASCII slug that "
    "fans of the system would recognise: 2-6 lowercase letters, digits "
    "allowed, no spaces, no punctuation. Examples: \"coc\" for Call of "
    "Cthulhu, \"dnd\" for Dungeons & Dragons, \"pf2e\" for Pathfinder 2e, "
    "\"wfrp\" for Warhammer Fantasy Roleplay, \"trav\" for Traveller. "
    "Return JSON only: {\"short_name\": \"<slug>\"}"
)

_MODULE_PROMPT = (
    "You receive the filename and the opening of a tabletop RPG adventure "
    "module. Identify the module's official title — what a Game Master "
    "would call it at the table. Strip filename clutter (extensions, "
    "version suffixes, edition tags, page-range markers, scan-tool "
    "watermarks). Preserve the original language; do not translate. "
    "Return JSON only: {\"title\": \"<clean title>\"}"
)


def _heuristic_short_name(book_title: str) -> str:
    """Cheap fallback: take initials of the first ~3 capitalised words."""
    if not book_title:
        return "rpg"
    words = re.findall(r"[A-Za-z]+", book_title)
    if not words:
        return "rpg"
    initials = "".join(w[0] for w in words[:4]).lower()
    return initials[:6] or "rpg"


def _heuristic_module_title(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)  # strip extension
    name = re.sub(r"[_\-]+", " ", name).strip()
    return name or "Module"


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _provider_default_key(provider: str) -> str:
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


async def _resolve_fast_model(
    db: AsyncSession,
) -> tuple[str, str, str, str] | None:
    entry = await model_pool.get_fast(db)
    if entry is None:
        return None
    saved = admin_config.get_provider(entry.provider) or {}
    api_key = saved.get("api_key", "") or _provider_default_key(entry.provider)
    base_url = saved.get("base_url", "") or _provider_default_base_url(entry.provider)
    return entry.provider, entry.model, api_key, base_url


async def _ask_fast(
    db: AsyncSession, system_prompt: str, user_prompt: str
) -> dict | None:
    resolved = await _resolve_fast_model(db)
    if resolved is None:
        return None
    provider, model, api_key, base_url = resolved
    try:
        client = build_client(
            provider=provider, model=model, api_key=api_key, base_url=base_url
        )
    except (ValueError, TypeError):
        return None
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]
    chunks: list[str] = []
    try:
        async for chunk in client.stream_chat(messages, temperature=0.2):
            if chunk.delta:
                chunks.append(chunk.delta)
    except Exception as exc:  # noqa: BLE001 - cosmetic call, never bubble up
        logger.warning("fast model call failed: %s", exc)
        return None
    raw = _strip_code_fences("".join(chunks))
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _clean_short_name(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", value).lower()
    return s[:8]


async def get_or_generate_ruleset_short_name(
    db: AsyncSession, rs: Ruleset
) -> str:
    """Cached fast-model slug for a ruleset; falls back to initials."""
    if rs.short_name:
        return rs.short_name
    snippet = ""
    parsed = rs.parsed_v6 or {}
    if isinstance(parsed, dict):
        core = parsed.get("core_rules")
        if isinstance(core, str):
            snippet = core[:1500]
    user_prompt = (
        f"Rulebook title: {rs.book_title or 'Unknown'}\n\n"
        f"Excerpt:\n{snippet or '(no excerpt available)'}"
    )
    payload = await _ask_fast(db, _RULESET_PROMPT, user_prompt)
    candidate = ""
    if payload and isinstance(payload.get("short_name"), str):
        candidate = _clean_short_name(payload["short_name"])
    if not candidate:
        candidate = _heuristic_short_name(rs.book_title or "")
    rs.short_name = candidate
    await db.commit()
    return candidate


async def _generate_module_title(
    db: AsyncSession, filename: str, markdown: str
) -> str:
    snippet = (markdown or "")[:2000]
    user_prompt = (
        f"Filename: {filename}\n\n"
        f"Opening:\n{snippet or '(no content available)'}"
    )
    payload = await _ask_fast(db, _MODULE_PROMPT, user_prompt)
    candidate = ""
    if payload and isinstance(payload.get("title"), str):
        candidate = payload["title"].strip()
    if not candidate:
        candidate = _heuristic_module_title(filename)
    return candidate[:120]


async def get_or_generate_module_title(
    db: AsyncSession, row: ParsedModule
) -> str:
    """Cached fast-model clean title for a persisted module row.

    On cache hit returns immediately; on miss runs the LLM, writes the
    result back to `parsed_modules.extracted_title`, and returns it. The
    write is fire-and-forget from the caller's perspective — no need for
    the route to commit.
    """
    if row.extracted_title:
        return row.extracted_title
    title = await _generate_module_title(db, row.filename, row.markdown)
    row.extracted_title = title
    await db.commit()
    return title


async def extract_module_title(
    db: AsyncSession, filename: str, markdown: str
) -> str:
    """One-shot title extraction for callers without a persisted row.

    Prefer `get_or_generate_module_title` whenever the caller already has
    the `ParsedModule` — that path caches the result. This helper exists
    for legacy / pre-persistence flows only.
    """
    return await _generate_module_title(db, filename, markdown)
