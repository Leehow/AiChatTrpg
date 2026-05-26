"""Keyword search over a parsed_v6 ruleset's `rule_packages` and
`parameter_families`.

This is the chatrpg port of chatlab's `search_ruleset_context` +
`execute_search_rules` flow. The GM emits `[SEARCH_RULES query="..."]`
(or `[SEARCH_RULES package_id="combat"]` / `[SEARCH_RULES family_id="weapon"
entry="knife"]`) in their reply, postprocess parses the marker, this module
does the actual lookup, and the result is injected as a `role=system`
chat row so the next turn the GM sees the cited rule excerpt or family
entry verbatim.

Why server-side and not LLM function calling: chatlab's pattern is the
GM treats markers as a uniform escape hatch — every special directive is a
text marker, never a tool_call response. That keeps the streaming path
simple (no tool_call schema management per-provider) and lets every model
backend behave identically. Chatrpg follows the same pattern.

Output shape:

    SearchResult.text → markdown the GM will see in chat history
    SearchResult.empty_reason → set when nothing matched (so the marker
                                still gets a reply explaining why)

Important: do NOT dump entire package bodies (they're 30K+ chars each).
We surface either: a single matched section / table row, OR a one-screen
excerpt around the keyword. The full text stays out of the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_MAX_PACKAGE_EXCERPT = 1600   # chars per matched package section
_MAX_FAMILY_ENTRY_BLOB = 800  # chars when serialising a single family entry
_MAX_HITS = 4
_KEYWORD_SPLIT_RE = re.compile(r"[\s,，、；;:：()（）/\\]+")
# ASCII char ranges: alphanumerics + Chinese characters (CJK Unified Ideographs).
_TOKEN_FILTER_RE = re.compile(r"[A-Za-z0-9一-鿿]+")


@dataclass
class SearchHit:
    source: str          # "package" | "family"
    id: str              # package_id or family_id
    name: str            # human-readable label
    snippet: str         # the actual rules text the GM should see
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    empty_reason: str = ""

    def to_markdown(self) -> str:
        if not self.hits:
            return self.empty_reason or "_(no rule content matched)_"
        parts: list[str] = []
        for h in self.hits:
            head = f"### {h.source}: `{h.id}` — {h.name}".rstrip()
            parts.append(f"{head}\n{h.snippet.strip()}")
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Keyword tokenisation


def _tokenise(query: str) -> list[str]:
    """Split a query into searchable tokens. Keeps CJK runs intact so
    `战斗规则` matches `### 战斗` headings, and lowercases ASCII so
    `Combat` matches `combat`."""
    text = (query or "").strip()
    if not text:
        return []
    out: list[str] = []
    for piece in _KEYWORD_SPLIT_RE.split(text):
        for tok in _TOKEN_FILTER_RE.findall(piece):
            tok = tok.lower()
            if len(tok) >= 1 and tok not in out:
                out.append(tok)
            if len(out) >= 8:
                return out
    return out


# ---------------------------------------------------------------------------
# Rule package search


def _split_sections(content: str) -> list[tuple[str, str]]:
    """Split a markdown body into (heading, section_body) pairs. A section
    starts at any `#`-line; everything until the next `#`-line is the body.
    The first chunk before any heading shows up with heading=''."""
    if not content:
        return []
    lines = content.splitlines(keepends=True)
    sections: list[tuple[str, str]] = []
    current_head = ""
    current_buf: list[str] = []
    for line in lines:
        if re.match(r"^#{1,6}\s", line):
            if current_buf:
                sections.append((current_head, "".join(current_buf)))
                current_buf = []
            current_head = line.strip().lstrip("#").strip()
        else:
            current_buf.append(line)
    if current_buf:
        sections.append((current_head, "".join(current_buf)))
    return sections


def _score_section(heading: str, body: str, tokens: list[str]) -> int:
    """How many query tokens hit this section? Headings count double so a
    section literally titled the keyword wins over a passing mention."""
    if not tokens:
        return 0
    h_low = (heading or "").lower()
    b_low = (body or "").lower()
    score = 0
    for tok in tokens:
        if tok in h_low:
            score += 2
        if tok in b_low:
            score += 1
    return score


def _trim_excerpt(body: str, tokens: list[str], limit: int = _MAX_PACKAGE_EXCERPT) -> str:
    """Return up to `limit` chars of `body`, anchored on the first matched
    token when possible so the GM sees the relevant paragraph."""
    if not body:
        return ""
    if len(body) <= limit:
        return body.rstrip()
    body_low = body.lower()
    anchor = -1
    for tok in tokens:
        idx = body_low.find(tok)
        if idx != -1 and (anchor == -1 or idx < anchor):
            anchor = idx
    if anchor == -1:
        return body[:limit].rstrip() + "\n…"
    start = max(0, anchor - 200)
    end = min(len(body), start + limit)
    excerpt = body[start:end].rstrip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(body):
        excerpt = excerpt + "\n…"
    return excerpt


def _search_packages(
    pkgs: list[dict[str, Any]],
    descriptors: dict[str, dict[str, Any]],
    tokens: list[str],
    direct_id: str | None,
) -> list[SearchHit]:
    out: list[SearchHit] = []
    if direct_id:
        # Caller asked for `[SEARCH_RULES package_id="combat"]`. With a
        # query we return the best-matching section; without one, return a
        # head excerpt + section TOC so the GM can refine to a specific
        # heading next.
        for pkg in pkgs:
            if not isinstance(pkg, dict):
                continue
            pid = str(pkg.get("package_id") or "").strip()
            if pid != direct_id:
                continue
            content = str(pkg.get("content") or "")
            sections = _split_sections(content) or [("", content)]
            if tokens:
                ranked = sorted(
                    ((_score_section(h, b, tokens), h, b) for h, b in sections),
                    key=lambda t: -t[0],
                )
                if ranked and ranked[0][0] > 0:
                    score, head, body = ranked[0]
                    snippet = _trim_excerpt(body, tokens)
                    if head:
                        snippet = f"**{head}**\n\n{snippet}"
                    out.append(SearchHit(
                        source="package", id=pid,
                        name=descriptors.get(pid, {}).get("title") or pid,
                        snippet=snippet,
                        extra={"section": head, "score": score},
                    ))
                    return out
            # No-query (or no token hit) path: head excerpt + section TOC.
            head_excerpt = content[:_MAX_PACKAGE_EXCERPT].rstrip()
            heads = [h for h, _ in sections if h]
            if heads:
                toc_lines = [f"- {h}" for h in heads[:30]]
                head_excerpt = (
                    head_excerpt
                    + "\n\n**Sections (use `query=` to drill in):**\n"
                    + "\n".join(toc_lines)
                )
            out.append(SearchHit(
                source="package", id=pid,
                name=descriptors.get(pid, {}).get("title") or pid,
                snippet=head_excerpt,
                extra={"section": "(overview)"},
            ))
            return out
        return out
    # Free-text search across all packages
    candidates: list[tuple[int, str, str, str, dict]] = []
    for pkg in pkgs:
        if not isinstance(pkg, dict):
            continue
        pid = str(pkg.get("package_id") or "").strip()
        if not pid:
            continue
        content = str(pkg.get("content") or "")
        for head, body in _split_sections(content) or [("", content)]:
            score = _score_section(head, body, tokens)
            if score > 0:
                candidates.append((score, pid, head, body, descriptors.get(pid) or {}))
    candidates.sort(key=lambda t: -t[0])
    for score, pid, head, body, desc in candidates[:_MAX_HITS]:
        snippet = _trim_excerpt(body, tokens)
        if head:
            snippet = f"**{head}**\n\n{snippet}"
        out.append(SearchHit(
            source="package", id=pid,
            name=desc.get("title") or pid,
            snippet=snippet,
            extra={"section": head, "score": score},
        ))
    return out


# ---------------------------------------------------------------------------
# Parameter family search


def _serialise_entry(entry: Any) -> str:
    """Render a single family entry as compact markdown. Lists/dicts get
    bullet'd k:v pairs; strings come through verbatim. Caps total length so
    a single huge weapon row can't blow the context budget."""
    if isinstance(entry, str):
        return entry[:_MAX_FAMILY_ENTRY_BLOB]
    if isinstance(entry, dict):
        lines: list[str] = []
        for k, v in entry.items():
            if v is None or v == "":
                continue
            text = v if isinstance(v, str) else str(v)
            lines.append(f"- **{k}**: {text}")
        body = "\n".join(lines)
        return body[:_MAX_FAMILY_ENTRY_BLOB]
    return str(entry)[:_MAX_FAMILY_ENTRY_BLOB]


def _entry_search_text(entry: Any) -> str:
    """Lowercased blob used for substring matching. Concats name/id/keys."""
    if isinstance(entry, str):
        return entry.lower()
    if isinstance(entry, dict):
        chunks: list[str] = []
        for k in ("name", "title", "label", "id", "key", "english_name", "canonical_name"):
            v = entry.get(k)
            if isinstance(v, str):
                chunks.append(v)
        return " ".join(chunks).lower()
    return ""


def _iter_family_entries(family: dict[str, Any]) -> list[Any]:
    """Normalise the various `.json` shapes into a flat entry list."""
    blob = family.get("json")
    if isinstance(blob, list):
        return blob
    if isinstance(blob, dict):
        for key in ("entries", "items", "options", "tables", "rows", "values"):
            nested = blob.get(key)
            if isinstance(nested, list):
                return nested
        # dict-of-dicts: turn into list[dict] keeping the key as `id`
        out: list[Any] = []
        for k, v in blob.items():
            if isinstance(v, dict):
                merged = dict(v)
                merged.setdefault("id", k)
                out.append(merged)
        return out
    return []


def _search_families(
    fams: list[dict[str, Any]],
    tokens: list[str],
    direct_family_id: str | None,
    direct_entry: str | None,
) -> list[SearchHit]:
    out: list[SearchHit] = []
    for fam in fams:
        if not isinstance(fam, dict):
            continue
        fid = str(fam.get("family_id") or "").strip()
        if not fid:
            continue
        if direct_family_id and fid != direct_family_id:
            continue
        entries = _iter_family_entries(fam)
        for e in entries:
            blob_low = _entry_search_text(e)
            if direct_entry:
                if direct_entry.lower() not in blob_low:
                    continue
            elif tokens:
                if not all(tok in blob_low for tok in tokens):
                    continue
            else:
                continue
            label = ""
            if isinstance(e, dict):
                label = (
                    str(e.get("name") or e.get("title") or e.get("label") or e.get("id") or "")
                    or fid
                )
            out.append(SearchHit(
                source="family", id=fid,
                name=label,
                snippet=_serialise_entry(e),
            ))
            if len(out) >= _MAX_HITS:
                return out
    return out


# ---------------------------------------------------------------------------
# Public entrypoint


def search_ruleset(
    parsed_v6: dict[str, Any] | None,
    *,
    query: str = "",
    package_id: str | None = None,
    family_id: str | None = None,
    entry: str | None = None,
) -> SearchResult:
    """Run the keyword search. The marker arguments map directly:
    `[SEARCH_RULES query="..."]` → `query=...`
    `[SEARCH_RULES package_id="combat"]` → `package_id=...`
    `[SEARCH_RULES family_id="weapon" entry="knife"]` → `family_id`+`entry`

    The three modes can be mixed: a `package_id` AND `query` will return
    the best section of that package matching the query."""
    parsed = parsed_v6 or {}
    tokens = _tokenise(query)
    pkgs = parsed.get("rule_packages") if isinstance(parsed.get("rule_packages"), list) else []
    fams = parsed.get("parameter_families") if isinstance(parsed.get("parameter_families"), list) else []
    descriptors: dict[str, dict[str, Any]] = {}
    manifest = parsed.get("discovery_manifest") if isinstance(parsed.get("discovery_manifest"), dict) else {}
    desc_list = manifest.get("detailed_rule_packages") or []
    for d in desc_list:
        if isinstance(d, dict):
            pid = str(d.get("package_id") or "").strip()
            if pid:
                descriptors[pid] = d

    hits: list[SearchHit] = []
    if package_id or (tokens and pkgs):
        hits.extend(_search_packages(pkgs, descriptors, tokens, package_id))
    if (family_id or entry or (tokens and fams)) and len(hits) < _MAX_HITS:
        hits.extend(
            _search_families(fams, tokens, family_id, entry)[: _MAX_HITS - len(hits)]
        )

    result = SearchResult(query=query or "", hits=hits)
    if not hits:
        bits = []
        if package_id:
            bits.append(f"package_id=`{package_id}` not found")
        if family_id:
            bits.append(f"family_id=`{family_id}` not found")
        if entry:
            bits.append(f"entry `{entry}` did not match any family")
        if query and not (package_id or family_id or entry):
            bits.append(f"query `{query}` matched nothing")
        result.empty_reason = "; ".join(bits) or "no search arguments supplied"
    return result
