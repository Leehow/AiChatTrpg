"""Run the grep retrieval agent against a ruleset's parsed_v6 (or a parsed
module) and format the result as a system-message body for IC injection.

This sits between ``trpg_ic_runner._stream_with_fresh_db`` and the generic
``GrepRetrievalAgent``:
- Builds searchable sources from parsed_v6 / parsed_module
- Configures bilingual ReAct prompts (Chinese-English bridging — the GM
  reads English equipment names off the PC card but the parser ships
  Chinese-language entries; without bilingual variants grep finds zero)
- Calls the agent and renders Markdown the GM will read on the next turn

If the LLM call fails, falls back to the single-pass keyword search via
``trpg_ruleset_search.search_ruleset`` so the GM still gets something
rather than silently nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.grep_retrieval import (
    GrepRetrievalAgent,
    GrepRetrievalPromptSpec,
)
from agents.grep_retrieval.runtime_openai import (
    make_openai_runtime,
    resolve_openai_compat_base_url,
)
from services.trpg_ruleset_sources import build_ruleset_sources

logger = logging.getLogger("chatrpg.trpg")


_RULES_GREP_AGENT = GrepRetrievalAgent(
    runtime=make_openai_runtime(),
    prompt_spec=GrepRetrievalPromptSpec(
        agent_name="TRPG in-play rules retrieval agent",
        task_description=(
            "search the parsed ruleset for the exact entry, parameter, "
            "or procedure the GM needs to resolve the current turn"
        ),
        source_scope_description=(
            "rule packages (procedures), parameter family entries (weapons, "
            "skills, occupations, items, spells, etc.), and the worldview "
            "companion text"
        ),
        source_scope_lines=(
            "rule_package: full markdown for one procedure (combat, "
            "investigation, sanity, …)",
            "param_entry: one canonical entry — name, aliases, category, "
            "skill, damage, range, tags, search hint",
            "param_family: directory listing for a family (entry counts, "
            "indexing fields, selection note)",
            "companion: the worldview / scene guide",
        ),
        bilingual_search=True,
        extra_rules=(
            "When the user message and source content use different "
            "languages, ALWAYS try at least one search in each language "
            "before giving up.",
            "Common bridge pattern: PC card lists the English label "
            "(\"folding knife\"/\"switchblade\") while the ruleset entry "
            "is Chinese (\"折刀\"/\"小刀\"). Try short noun roots like "
            "\"knife\"/\"刀\" if longer phrases miss.",
            "Prefer a param_entry over a param_family directory when both "
            "match — the entry has the canonical fields the GM needs.",
        ),
        result_heading="## Rule Lookup",
        max_result_sources=3,
    ),
)


def _build_recent_context(recent_messages: list[dict[str, Any]] | None) -> str:
    """Render the last few messages as a single short block for the agent."""
    if not recent_messages:
        return ""
    lines: list[str] = []
    for msg in recent_messages[-6:]:
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        if not role or not content:
            continue
        lines.append(f"[{role}] {content[:240]}")
    return "\n".join(lines)


def _format_seed_query(req: dict[str, Any]) -> str:
    """Stitch the marker attrs into a short user-facing query string."""
    parts: list[str] = []
    for key in ("query", "package_id", "family_id", "entry"):
        val = str(req.get(key) or "").strip()
        if val:
            parts.append(f"{key}={val}")
    return ", ".join(parts) or "(empty)"


async def grep_search_ruleset(
    *,
    parsed_v6: dict[str, Any] | None,
    req: dict[str, Any],
    model: str,
    base_url: str,
    api_key: str,
    provider: str = "",
    recent_messages: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Run the grep retrieval agent over a parsed_v6 ruleset.

    Returns ``(markdown_body, hit_count)``. Markdown is empty when nothing
    relevant was found; the caller decides whether to skip injection or
    inject a "no match" placeholder.

    ``provider`` is optional but recommended: chatrpg's model-pool returns
    an empty ``base_url`` for native providers like Gemini (because the
    native SDK doesn't need one). The grep agent speaks OpenAI tool_calls
    so it needs an OpenAI-compatible URL — we look it up by provider name
    when ``base_url`` is missing.
    """
    sources = build_ruleset_sources(parsed_v6 or {})
    if not sources:
        return "", 0

    resolved_base_url = resolve_openai_compat_base_url(provider, base_url)
    if not resolved_base_url:
        # No usable endpoint — skip the agent and try the keyword fallback
        # so the GM still gets *something* on the next turn.
        logger.info(
            "[grep-search] no openai-compat base_url for provider=%r — "
            "falling back to keyword search.",
            provider,
        )
        return _fallback_keyword(parsed_v6 or {}, req)

    primary_query = (
        str(req.get("query") or "").strip()
        or str(req.get("entry") or "").strip()
        or str(req.get("package_id") or "").strip()
        or str(req.get("family_id") or "").strip()
    )
    if not primary_query:
        return "", 0

    # Hint the agent which family / package the GM aimed at, so it can
    # filter via the source_type tool argument and avoid wasting iterations
    # in unrelated rule packages.
    scope_hints: list[str] = []
    if str(req.get("family_id") or "").strip():
        scope_hints.append(
            f"GM-supplied family_id: {req['family_id']} — prefer "
            f"param_entry / param_family sources for this family."
        )
    if str(req.get("package_id") or "").strip():
        scope_hints.append(
            f"GM-supplied package_id: {req['package_id']} — start with "
            f"the matching rule_package source."
        )
    if str(req.get("entry") or "").strip():
        scope_hints.append(
            f"GM-supplied entry name: {req['entry']} — try this verbatim "
            f"first, then short noun roots and likely translation."
        )

    try:
        payload = await _RULES_GREP_AGENT.retrieve(
            message=primary_query,
            recent_context=_build_recent_context(recent_messages),
            sources=sources,
            model=model,
            base_url=resolved_base_url,
            api_key=api_key,
            seed_terms=_format_seed_query(req),
            scope_hints=tuple(scope_hints),
        )
    except Exception as exc:
        logger.warning(
            "[grep-search] agent failed for %s: %s",
            _format_seed_query(req), exc, exc_info=True,
        )
        return _fallback_keyword(parsed_v6 or {}, req)

    # Pass an empty heading so the IC runner can add its own contextual
    # one ("## Rule lookup — switchblade") without producing duplicate
    # `## Rule Lookup` headers stacked in the saved message.
    formatted = _RULES_GREP_AGENT.format_context(
        payload,
        sources=sources,
        heading="",
    )
    if formatted:
        # ``format_retrieval_context`` joins blocks with "\n\n"; with
        # heading="" it leaves a leading newline pair we strip here.
        formatted = formatted.lstrip("\n").strip()
    if formatted:
        sources_count = 0
        if isinstance(payload, dict):
            items = payload.get("sources")
            if isinstance(items, list):
                sources_count = len(items)
        return formatted, sources_count

    # Agent ran cleanly but found nothing — fall back to keyword search so
    # the GM at least sees the closest text match instead of silence.
    return _fallback_keyword(parsed_v6 or {}, req)


def _fallback_keyword(
    parsed_v6: dict[str, Any],
    req: dict[str, Any],
) -> tuple[str, int]:
    """Single-pass keyword grep — last-resort fallback when the agent
    fails. Mirrors the pre-Wave-3 behaviour so we degrade gracefully."""
    try:
        from services.trpg_ruleset_search import search_ruleset
    except Exception:
        return "", 0
    try:
        result = search_ruleset(
            parsed_v6,
            query=str(req.get("query") or ""),
            package_id=req.get("package_id"),
            family_id=req.get("family_id"),
            entry=req.get("entry"),
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[grep-search] keyword fallback also failed: %s", exc)
        return "", 0
    body = result.to_markdown() if hasattr(result, "to_markdown") else ""
    hits = getattr(result, "hits", None)
    return body, (len(hits) if isinstance(hits, list) else 0)


def build_module_sources(parsed_module: Any) -> list[dict[str, str]]:
    """Build grep-searchable sources from a ParsedModule ORM row.

    Today this is intentionally narrow: ``briefing_md`` (the GM-facing
    summary) plus the full ``markdown`` body cut into ~6k-char chunks at
    blank-line boundaries. We deliberately don't try to honour the
    semantic_steps pipeline output because that's just the parser's
    progress log, not scene-by-scene narrative.
    """
    if parsed_module is None:
        return []
    out: list[dict[str, str]] = []
    title = str(getattr(parsed_module, "extracted_title", "") or "module")
    briefing = str(getattr(parsed_module, "briefing_md", "") or "").strip()
    if briefing:
        out.append({
            "id": "module:briefing",
            "source_type": "module_briefing",
            "label": f"Module / {title} / briefing",
            "content": briefing,
        })

    markdown = str(getattr(parsed_module, "markdown", "") or "").strip()
    if markdown:
        chunks = _chunk_markdown(markdown, max_chars=6000)
        for idx, chunk in enumerate(chunks):
            out.append({
                "id": f"module:body:{idx}",
                "source_type": "module_body",
                "label": f"Module / {title} / body §{idx + 1}",
                "content": chunk,
            })
    return out


def _chunk_markdown(text: str, *, max_chars: int) -> list[str]:
    """Split markdown into ~``max_chars`` chunks at blank-line boundaries.
    Falls back to fixed-width slicing if no blank lines are found."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in text.split("\n\n"):
        plen = len(para) + 2
        if current_len + plen > max_chars and current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        current.append(para)
        current_len += plen
    if current:
        chunks.append("\n\n".join(current).strip())
    return [c for c in chunks if c]


async def grep_search_module(
    *,
    parsed_module: Any,
    query: str,
    model: str,
    base_url: str,
    api_key: str,
    recent_messages: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Run the grep agent over a parsed module's text. Mirrors the API
    of ``grep_search_ruleset`` so the IC runner can wire both with the
    same shape."""
    sources = build_module_sources(parsed_module)
    if not sources or not str(query or "").strip():
        return "", 0

    spec = GrepRetrievalPromptSpec(
        agent_name="TRPG module retrieval agent",
        task_description=(
            "search the parsed module text for the GM-facing answer "
            "to the current lookup"
        ),
        source_scope_description=(
            "the GM briefing and the body of the parsed module"
        ),
        source_scope_lines=(
            "module_briefing: short GM-facing summary",
            "module_body: paragraph-aligned chunks of the full module text",
        ),
        bilingual_search=True,
        extra_rules=(
            "Quote the module's own wording when possible — the GM will "
            "paraphrase, so concrete names / numbers / quoted dialogue "
            "matter.",
        ),
        result_heading="## Module Lookup",
        max_result_sources=3,
    )
    agent = GrepRetrievalAgent(runtime=make_openai_runtime(), prompt_spec=spec)
    try:
        payload = await agent.retrieve(
            message=str(query or "").strip(),
            recent_context=_build_recent_context(recent_messages),
            sources=sources,
            model=model,
            base_url=base_url,
            api_key=api_key,
            seed_terms=str(query or "").strip(),
        )
    except Exception as exc:
        logger.warning("[grep-search] module agent failed: %s", exc, exc_info=True)
        return "", 0
    formatted = agent.format_context(
        payload, sources=sources, heading="## Module Lookup",
    )
    sources_count = 0
    if isinstance(payload, dict):
        items = payload.get("sources")
        if isinstance(items, list):
            sources_count = len(items)
    return formatted, sources_count
