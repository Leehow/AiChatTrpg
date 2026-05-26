"""Pure helpers + prompts + dataclasses for the grep retrieval agent.

Faithful port of chatlab's `agents/grep_retrieval_agent.py` lines 1-300:
- dataclasses for config, runtime, prompt spec
- source map / type inference
- pattern compilation, snippet extraction
- grep_sources, format_grep_results, read_source
- build_system_prompt, build_user_prompt
- format_retrieval_context

Split out from `agent.py` to keep each module under 400 lines per repo
policy. The behavioral logic is unchanged from chatlab — only the file
layout differs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

SourceLike = Mapping[str, Any]


@dataclass(frozen=True)
class GrepRetrievalAgentConfig:
    system_prompt: str
    user_prompt: str
    source_type_options: Tuple[str, ...] = ("any",)
    max_iterations: int = 6
    force_output_at: int = 4
    max_grep_hits: int = 8
    max_snippet_chars: int = 420
    max_source_chars: int = 2200


@dataclass(frozen=True)
class GrepRetrievalRuntime:
    build_client: Callable[..., Any]
    apply_request_defaults: Callable[[Dict[str, Any]], Dict[str, Any]]
    extract_json: Callable[[str], Any]


@dataclass(frozen=True)
class GrepRetrievalPromptSpec:
    agent_name: str = "grep retrieval agent"
    task_description: str = (
        "search the provided text sources and return only the minimum extra "
        "context needed for the main model"
    )
    source_scope_description: str = "provided text sources"
    source_scope_lines: Tuple[str, ...] = ()
    bilingual_search: bool = False
    extra_rules: Tuple[str, ...] = ()
    result_heading: str = "## Retrieval Notes"
    max_result_sources: int = 4


def build_source_map(sources: Sequence[SourceLike]) -> Dict[str, Dict[str, Any]]:
    return {
        str(source["id"]): dict(source)
        for source in sources
        if source.get("id")
    }


def infer_source_type_options(sources: Sequence[SourceLike]) -> Tuple[str, ...]:
    values = tuple(
        sorted({
            str(source.get("source_type") or "").strip()
            for source in sources
            if str(source.get("source_type") or "").strip()
        })
    )
    if not values:
        return ("any",)
    if "any" in values:
        return values
    return ("any",) + values


def build_system_prompt(spec: GrepRetrievalPromptSpec) -> str:
    lines = [
        f"You are a {spec.agent_name}.",
        "",
        f"Your task is to {spec.task_description}.",
        "",
        "Data scope:",
        f"- {spec.source_scope_description}",
    ]
    for line in spec.source_scope_lines:
        if str(line).strip():
            lines.append(f"- {str(line).strip()}")

    lines.extend([
        "",
        "Workflow:",
        "1. Use grep_search first with short, concrete search terms.",
        "1a. Do not rely on a single exact phrase. When the first search is "
        "weak or empty, try several keyword variants.",
    ])
    if spec.bilingual_search:
        lines.extend([
            "1b. Search bilingually when needed. If the user asks in Chinese, "
            "also consider likely English search terms.",
            "If the user asks in English, also consider likely Chinese search "
            "terms.",
            "1c. Source labels, categories, and entry names may be in a "
            "different language from the user message.",
        ])
    lines.extend([
        "1d. Good keyword variants include: original phrase, likely "
        "translated term, singular/plural form, partial proper name, "
        "slug/category word, and shorter noun phrase.",
        "2. If a hit looks relevant, use read_source to inspect it.",
        "3. Stop once you have enough evidence.",
        "4. Return ONLY JSON in this shape:",
        "{",
        '  "relevant": true,',
        '  "summary": "short note about what was found",',
        '  "sources": [',
        "    {",
        '      "source_id": "exact id",',
        '      "label": "human label",',
        '      "excerpt": "short directly useful excerpt"',
        "    }",
        "  ]",
        "}",
        "",
        "Rules:",
        f"- Max {spec.max_result_sources} sources.",
        "- Do not answer the user directly.",
        "- Do not invent source ids, labels, or excerpts.",
        '- If nothing useful is found, return: {"relevant": false, '
        '"summary": "nothing useful found", "sources": []}',
        "- Prefer exact rules text, option descriptions, and concrete "
        "entries over vague matches.",
    ])
    for rule in spec.extra_rules:
        if str(rule).strip():
            lines.append(f"- {str(rule).strip()}")
    return "\n".join(lines)


def build_user_prompt(
    *,
    message: str,
    recent_context: str,
    sources: Sequence[SourceLike],
    seed_terms: str = "",
    scope_hints: Sequence[str] = (),
    extra_sections: Sequence[Tuple[str, str]] = (),
) -> str:
    lines = [
        "User message:",
        message or "(none)",
        "",
        "Recent context:",
        recent_context or "(none)",
        "",
        f"Initial search hints: {seed_terms or '(none)'}",
        f"Available sources: {len(sources)}",
    ]
    if scope_hints:
        lines.append("Scope hints:")
        for hint in scope_hints:
            if str(hint).strip():
                lines.append(f"- {str(hint).strip()}")
    for title, content in extra_sections:
        lines.extend(["", f"{title}:", content or "(none)"])
    lines.extend(["", "Begin searching now."])
    return "\n".join(lines)


def _compile_pattern(keyword: str) -> re.Pattern[str]:
    try:
        return re.compile(keyword, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(keyword), re.IGNORECASE)


def _build_snippet(text: str, start: int, end: int, *, max_snippet_chars: int) -> str:
    left = max(0, start - max_snippet_chars // 2)
    right = min(len(text), end + max_snippet_chars // 2)
    snippet = text[left:right].strip().replace("\n\n", "\n")
    if left > 0:
        snippet = "..." + snippet
    if right < len(text):
        snippet = snippet + "..."
    return snippet


def grep_sources(
    sources: Sequence[SourceLike],
    keyword: str,
    *,
    source_type: str = "any",
    max_grep_hits: int = 8,
    max_snippet_chars: int = 420,
) -> List[Dict[str, Any]]:
    pattern = _compile_pattern(keyword)
    hits: List[Dict[str, Any]] = []
    for source in sources:
        if source_type != "any" and source.get("source_type") != source_type:
            continue
        content = str(source.get("content") or "")
        match = pattern.search(content)
        if not match:
            continue
        line_no = content.count("\n", 0, match.start()) + 1
        hits.append({
            "source_id": str(source.get("id") or ""),
            "label": str(source.get("label") or ""),
            "source_type": str(source.get("source_type") or ""),
            "line": line_no,
            "snippet": _build_snippet(
                content,
                match.start(),
                match.end(),
                max_snippet_chars=max_snippet_chars,
            ),
        })
        if len(hits) >= max_grep_hits:
            break
    return hits


def format_grep_results(keyword: str, hits: Sequence[Dict[str, Any]]) -> str:
    if not hits:
        return f'No matches for "{keyword}"'
    lines = [f'Found {len(hits)} match(es) for "{keyword}":']
    for hit in hits:
        lines.append(
            f"\n[{hit['source_id']}] {hit['label']} "
            f"(type={hit['source_type']}, line={hit['line']})\n"
            f"{hit['snippet']}\n---"
        )
    return "\n".join(lines)


def read_source(
    source_map: Dict[str, Dict[str, Any]],
    source_id: str,
    *,
    max_source_chars: int = 2200,
) -> str:
    source = source_map.get(source_id)
    if not source:
        return f"Unknown source_id: {source_id}"
    content = str(source.get("content") or "").strip()
    if len(content) > max_source_chars:
        content = content[:max_source_chars] + "\n...[truncated]"
    return f"[{source_id}] {source.get('label')}\n{content}"


def format_retrieval_context(
    payload: Dict[str, Any] | None,
    source_map: Dict[str, Dict[str, Any]],
    *,
    heading: str = "## Retrieval Notes",
    max_sources: int = 4,
    fallback_excerpt_chars: int = 900,
) -> str:
    if not isinstance(payload, dict) or not payload.get("relevant"):
        return ""
    items = payload.get("sources")
    if not isinstance(items, list) or not items:
        return ""

    blocks = [heading]
    summary = str(payload.get("summary") or "").strip()
    if summary:
        blocks.append(summary)

    added = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        source = source_map.get(source_id, {})
        label = str(item.get("label") or source.get("label") or source_id).strip()
        excerpt = str(item.get("excerpt") or "").strip()
        if not excerpt:
            excerpt = str(source.get("content") or "").strip()[:fallback_excerpt_chars]
        if not label or not excerpt:
            continue
        blocks.append(f"### {label}\n{excerpt}")
        added += 1
        if added >= max_sources:
            break

    return "\n\n".join(blocks) if added else ""
