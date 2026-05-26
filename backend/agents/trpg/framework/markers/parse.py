"""Marker parsing — extracts structured `[TAG ...]` markers from assistant text.

Two surface syntaxes are supported (mirrors what chatlab GMs naturally emit):

  1. Self-closing: `[KIND key1=val key2="val with spaces"]`
  2. Block form:    `[KIND key=val]inline content[/KIND]`

Output is a list of ParsedMarker. Semantic interpretation lives in
`markers/apply.py` — this file only does structural extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

MarkerKind = Literal[
    "roll",
    "set_scene",
    "update_memory",
    "create_npc",
    "update_npc",
    "update_npc_params",
    "reveal_name",
    "search_module",
    "update_pc",
    "advance_time",
    "create_character",
    "update_character",
    # Catch-all for unrecognized but well-formed tags. Kept as a literal so
    # downstream consumers can still match on it without losing information.
    "unknown",
]

_KNOWN_KINDS: set[str] = {
    "roll",
    "set_scene",
    "update_memory",
    "create_npc",
    "update_npc",
    "update_npc_params",
    "reveal_name",
    "search_module",
    "update_pc",
    "advance_time",
    "create_character",
    "update_character",
}


@dataclass
class ParsedMarker:
    kind: MarkerKind
    args: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    raw_text: str = ""
    span: tuple[int, int] = (0, 0)


# Match an opening tag's name + attribute string. We allow lowercase names with
# letters / digits / underscores. Attribute values are either bare tokens
# (no whitespace) or double-quoted strings.
_OPEN_TAG = re.compile(
    r"\[\s*([A-Za-z_][A-Za-z0-9_]*)((?:\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:\"[^\"]*\"|[^\s\]]+))*)\s*\]",
)
_CLOSE_TAG_TPL = r"\[\s*/\s*{name}\s*\]"
_ARG_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\"([^\"]*)\"|([^\s\]]+))",
)


def parse_markers(text: str) -> list[ParsedMarker]:
    """Walk `text` and pull out every `[TAG ...]` marker.

    Block-form `[TAG]…[/TAG]` markers absorb any inline content between the
    tags into `body`; self-closing `[TAG]` (no matching close tag) leave
    `body=""`."""
    if not text:
        return []
    out: list[ParsedMarker] = []
    pos = 0
    while pos < len(text):
        m = _OPEN_TAG.search(text, pos)
        if m is None:
            break
        name_raw = m.group(1)
        # Tag names like "/TAG" are close tags — skip them, they shouldn't
        # be matched here anyway because _OPEN_TAG forbids leading slash, but
        # be defensive.
        kind_norm = _normalize_kind(name_raw)
        # Try to find a matching close tag. Start hunting *after* the opening
        # tag so the same regex can't match the close.
        close_re = re.compile(
            _CLOSE_TAG_TPL.format(name=re.escape(name_raw)), re.IGNORECASE,
        )
        close_match = close_re.search(text, m.end())
        if close_match is not None:
            body = text[m.end():close_match.start()]
            end = close_match.end()
            raw = text[m.start():end]
        else:
            body = ""
            end = m.end()
            raw = text[m.start():end]
        args = _parse_args(m.group(2) or "")
        out.append(ParsedMarker(
            kind=kind_norm,  # type: ignore[arg-type]
            args=args,
            body=body,
            raw_text=raw,
            span=(m.start(), end),
        ))
        pos = end
    return out


def _normalize_kind(name: str) -> str:
    n = name.strip().lower()
    if n in _KNOWN_KINDS:
        return n
    return "unknown"


def _parse_args(arg_str: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for match in _ARG_PATTERN.finditer(arg_str):
        key = match.group(1)
        val = match.group(2) if match.group(2) is not None else match.group(3)
        args[key] = val
    return args
