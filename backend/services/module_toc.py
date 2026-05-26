"""Extract a structured table of contents from raw module markdown.

Two paths:

1. Cheap heuristic: walk the markdown, pull every `#`-prefixed heading.
   Always available, runs locally, doesn't need a model. Used as the
   immediate fallback when LLM extraction fails or no model is configured.

2. LLM rewrite: send the markdown to whatever model is currently the
   pool default and ask for a clean nested TOC. Better at recovering
   from rulebook quirks (titles formatted as bold lines, mid-paragraph
   section headers, etc.). Falls back to the heuristic on parse failure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from services import admin_config, model_pool

# Optional async callback for token-level streaming. We invoke it once
# per LLM chunk with (delta_text, total_chars_received). Throttling is
# the caller's job — we always fire on every delta.
TocChunkCallback = Callable[[str, int], Awaitable[None]]

# No size pre-check — we just send the whole thing to the LLM. If the
# model can't fit it, its API will return a clear error (e.g.
# "context_length_exceeded") which we surface verbatim. Different
# providers have different limits; hardcoding our own ceiling would
# only get in the way.

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_ANCHOR_RE = re.compile(r"[^\w一-鿿-]+")


@dataclass
class TOCEntry:
    title: str
    level: int
    anchor: str = ""
    # 1-based inclusive line range in the markdown the entry covers.
    # 0 means "unknown" — we couldn't pin the heading down to a line
    # (LLM TOC entry that doesn't appear verbatim in the doc, etc.).
    line_start: int = 0
    line_end: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _slug(title: str) -> str:
    """Cheap GitHub-style anchor — keeps unicode letters."""
    s = title.strip().lower()
    s = _ANCHOR_RE.sub("-", s)
    return s.strip("-")


def _normalize_title(s: str) -> str:
    """Lossy normalisation for fuzzy heading matching.

    Drops whitespace, punctuation, full/half-width variants — anything
    that the LLM might rewrite without changing the semantic title.
    Keeps letters and digits (incl. CJK).
    """
    out: list[str] = []
    for ch in s:
        if ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def annotate_with_lines(
    markdown: str, toc: list[TOCEntry]
) -> list[TOCEntry]:
    """Set line_start / line_end on each entry by walking the markdown.

    Strategy:
      1. Collect every `# heading` line with its line number.
      2. For each TOC entry in order, advance through the heading list
         and pick the first one whose normalised title matches.
      3. line_end of entry N = line_start of entry N+1 minus 1, or the
         document's last line for the trailing entry.

    Entries we can't locate are left at line_start=0 — the route is
    expected to surface that as "unknown" rather than guess.
    """
    if not toc:
        return toc
    lines = markdown.splitlines()
    # (line_index_0based, level, normalised_title)
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((i, len(m.group(1)), _normalize_title(m.group(2))))

    annotated: list[TOCEntry] = []
    cursor = 0
    for entry in toc:
        # Already pinned (e.g. by the LLM directly) — preserve the
        # caller's line_start and just bump the cursor past whatever
        # heading sits on that line so subsequent text matches stay in
        # document order.
        if entry.line_start > 0:
            for j in range(cursor, len(headings)):
                if headings[j][0] + 1 >= entry.line_start:
                    cursor = j + 1 if headings[j][0] + 1 == entry.line_start else j
                    break
            annotated.append(
                TOCEntry(
                    title=entry.title,
                    level=entry.level,
                    anchor=entry.anchor,
                    line_start=entry.line_start,
                )
            )
            continue

        target = _normalize_title(entry.title)
        if not target:
            annotated.append(
                TOCEntry(title=entry.title, level=entry.level, anchor=entry.anchor)
            )
            continue
        match_idx = -1
        # Prefer an exact-title match within the unconsumed tail. If
        # nothing matches exactly, allow a substring match (LLM might
        # have trimmed or expanded a title).
        for j in range(cursor, len(headings)):
            _, _, htitle = headings[j]
            if htitle == target:
                match_idx = j
                break
        if match_idx < 0:
            for j in range(cursor, len(headings)):
                _, _, htitle = headings[j]
                if target in htitle or htitle in target:
                    match_idx = j
                    break
        if match_idx < 0:
            annotated.append(
                TOCEntry(title=entry.title, level=entry.level, anchor=entry.anchor)
            )
            continue
        cursor = match_idx + 1
        annotated.append(
            TOCEntry(
                title=entry.title,
                level=entry.level,
                anchor=entry.anchor,
                line_start=headings[match_idx][0] + 1,  # 1-based
            )
        )

    # Second pass: fill line_end as the line just before the next
    # successfully-located entry's start (or end-of-document).
    total_lines = len(lines)
    for i, entry in enumerate(annotated):
        if entry.line_start <= 0:
            continue
        next_start = 0
        for j in range(i + 1, len(annotated)):
            if annotated[j].line_start > entry.line_start:
                next_start = annotated[j].line_start
                break
        entry.line_end = (next_start - 1) if next_start else total_lines

    return annotated


def heuristic_toc(markdown: str) -> list[TOCEntry]:
    """Pull every markdown heading. Cheap, no LLM."""
    seen: set[str] = set()
    out: list[TOCEntry] = []
    for match in _HEADING_RE.finditer(markdown):
        level = len(match.group(1))
        title = match.group(2).strip()
        if not title:
            continue
        anchor = _slug(title)
        # Disambiguate duplicates (chapter "Combat" appearing twice).
        base, n = anchor, 1
        while anchor in seen:
            anchor = f"{base}-{n}"
            n += 1
        seen.add(anchor)
        out.append(TOCEntry(title=title, level=level, anchor=anchor))
    return out


_TOC_PROMPT = (
    "You receive markdown extracted from a tabletop RPG rulebook or "
    "module. Each line is prefixed with its 1-based line number and a "
    "colon, like:\n"
    "  1: # Chapter 1\n"
    "  2:\n"
    "  3: Some body text...\n"
    "Identify the document's table of contents. Return JSON only, no "
    "prose. Schema:\n"
    '  {"toc": [{"title": str, "level": int 1-6, "line": int}, ...]}\n'
    "Rules:\n"
    "- One entry per real section heading.\n"
    "- `line` MUST be the exact line number where the heading appears "
    "(the prefix you see on that line). Never invent a number.\n"
    "- Skip running headers, page numbers, figure captions, copyright "
    "lines, etc.\n"
    "- Preserve the original heading language (do not translate).\n"
    "- Level reflects nesting depth (1 = top-level chapter).\n"
    "- Entries MUST be returned in document order (line numbers ascending).\n"
    "- If the document has no clear sections, return {\"toc\": []}.\n"
    "- Return ONLY the JSON object."
)


def _number_lines(markdown: str) -> str:
    """Prefix every line with `N: ` so the LLM can return exact line
    references. Variable-width line numbers keep the token cost low —
    the LLM doesn't care about column alignment.
    """
    return "\n".join(f"{i}: {line}" for i, line in enumerate(markdown.split("\n"), start=1))


async def _resolve_default_model(
    db: AsyncSession,
) -> tuple[str, str, str, str] | None:
    """Return (provider, model, api_key, base_url) for the pool default."""
    entry = await model_pool.get_default(db)
    if entry is None:
        return None
    saved = admin_config.get_provider(entry.provider) or {}
    api_key = saved.get("api_key", "") or _provider_default_key(entry.provider)
    base_url = saved.get("base_url", "") or _provider_default_base_url(entry.provider)
    return entry.provider, entry.model, api_key, base_url


def _provider_default_key(provider: str) -> str:
    # Codex-relay accepts any non-empty key; mirrors PROVIDER_DEFAULTS in
    # routes/llm_test.py without importing that module.
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    # Same one-of-a-kind default — keep in sync with llm_test if more
    # providers ever pick up a hard-coded base.
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # ```json\n...\n``` — drop fence + optional language tag
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


async def llm_toc(
    db: AsyncSession,
    markdown: str,
    on_chunk: TocChunkCallback | None = None,
) -> list[TOCEntry]:
    """Best-effort LLM TOC with line numbers. Falls back to heuristic.

    The markdown is sent line-numbered (`N: ...`) so the LLM can
    reference exact line positions in its output. Each TOC entry's
    `line` field is validated against `_HEADING_RE` to reject hallucinations
    — if the line doesn't point at a real markdown heading, we fall back
    to text-matching that entry through `annotate_with_lines`.
    """
    fallback = annotate_with_lines(markdown, heuristic_toc(markdown))
    resolved = await _resolve_default_model(db)
    if resolved is None:
        return fallback
    provider, model, api_key, base_url = resolved

    numbered = _number_lines(markdown)
    full_lines = markdown.split("\n")

    try:
        client = build_client(
            provider=provider, model=model, api_key=api_key, base_url=base_url
        )
    except (ValueError, TypeError):
        return fallback

    messages = [
        ChatMessage(role="system", content=_TOC_PROMPT),
        ChatMessage(role="user", content=numbered),
    ]
    chunks: list[str] = []
    total_chars = 0
    try:
        async for chunk in client.stream_chat(messages, temperature=0.2):
            if chunk.delta:
                chunks.append(chunk.delta)
                total_chars += len(chunk.delta)
                if on_chunk is not None:
                    try:
                        await on_chunk(chunk.delta, total_chars)
                    except Exception:
                        pass
    except Exception:
        return fallback

    raw = _strip_code_fences("".join(chunks))
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return fallback
    items = payload.get("toc") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return fallback

    out: list[TOCEntry] = []
    seen_anchors: set[str] = set()
    needs_text_match: list[int] = []  # indices that need annotate fallback
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        try:
            level = max(1, min(6, int(item.get("level") or 1)))
        except (TypeError, ValueError):
            level = 1
        if not title:
            continue
        anchor = _slug(title)
        base, n = anchor, 1
        while anchor in seen_anchors:
            anchor = f"{base}-{n}"
            n += 1
        seen_anchors.add(anchor)

        # Validate the LLM's line number — must (a) be in range, (b)
        # point at a real markdown heading line. Anything else, mark
        # for text-matching fallback below.
        line_start = 0
        try:
            raw_line = int(item.get("line") or 0)
        except (TypeError, ValueError):
            raw_line = 0
        if 1 <= raw_line <= len(full_lines):
            candidate = full_lines[raw_line - 1]
            if _HEADING_RE.match(candidate):
                line_start = raw_line

        entry = TOCEntry(title=title, level=level, anchor=anchor, line_start=line_start)
        out.append(entry)
        if line_start == 0:
            needs_text_match.append(len(out) - 1)

    if not out:
        return fallback

    # Text-match the entries the LLM didn't pin (or pinned wrong) — the
    # cursor inside annotate_with_lines preserves document order so even
    # partial fills don't mis-align the rest.
    if needs_text_match:
        annotated = annotate_with_lines(markdown, out)
        for idx in needs_text_match:
            if annotated[idx].line_start > 0:
                out[idx].line_start = annotated[idx].line_start

    # Fill line_end based on the next entry that has a known start.
    total_lines = len(full_lines)
    for i, entry in enumerate(out):
        if entry.line_start <= 0:
            continue
        next_start = 0
        for j in range(i + 1, len(out)):
            if out[j].line_start > entry.line_start:
                next_start = out[j].line_start
                break
        entry.line_end = (next_start - 1) if next_start else total_lines

    return out
