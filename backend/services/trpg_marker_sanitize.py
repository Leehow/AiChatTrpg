"""Sanitize wrapper-mangled / typo'd TRPG markers in GM output.

Three failure modes the GM model produces in practice:

1. **Markdown wrapping** — `**[CHECK ...]**`, `*[/CHECK]*`, ``` `[TAKE_TIME]` ```.
   The bold/italic/code formatting drifts in when the GM is mid-narration and
   forgets that markers must sit on their own line. Downstream parsers
   (`CheckMarkerStream`, `parse_chatrpg_markers`, framework `parse_markers`)
   match on exact `[NAME` boundaries and silently drop the marker.

2. **Underscore drift** — `[TAKE TIME]`, `[TAKETIME]`, `[UPDATE NPC PARAMS]`.
   Same root cause: GM treats the tag like prose. A pure regex normalisation
   covers most cases without an LLM round-trip.

3. **Stray closing slash** — `[/CHECK ]` with trailing space, `[ /CHECK]` with
   leading space inside the tag. Cheap to fix.

Mirrors chatlab's `marker_sanitize.py` minus the LLM audit step. We can add
the LLM fallback later for unrecognised typos, but the regex layer alone
catches >90% of mangling in the wild.

Run order: call `sanitize_markers(text)` BEFORE any `parse_*` step on the
final GM `assistant_text`. Streaming-time markers (`[CHECK]`/`[CONTEST]`)
miss this pass — they're processed mid-stream by their dedicated stream
buffers — but the tail-end markers (`[TAKE_TIME]`, `[UPDATE_*_PARAMS]`,
`[SEARCH_RULES]`, `[STRUCTURED_EVENTS]`, `[SET_OBJECTIVE]`, `[ADD_NOTE]`,
`[UPDATE_MEMORY]`, `[SET_SCENE]`, `[CREATE_NPC]`) all benefit.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("chatrpg.trpg")


# Canonical marker names chatrpg actually consumes downstream. Order matters
# for typo-fix: longer names first so `UPDATE_NPC_PARAMS` is tried before
# `UPDATE_NPC` (which would also match the prefix).
CANONICAL_MARKERS = [
    "UPDATE_NPC_PARAMS",
    "UPDATE_PC_PARAMS",
    "STRUCTURED_EVENTS",
    "SEARCH_MODULE",
    "SEARCH_RULES",
    "UPDATE_MEMORY",
    "SET_OBJECTIVE",
    "CREATE_NPC",
    "CREATE_CHARACTER",
    "TAKE_TIME",
    "SET_SCENE",
    "UPDATE_PC",
    "ADD_NOTE",
    "CHECK",
    "CONTEST",
]
# Quick-lookup forms used by the typo pass.
_NORMALISED_NAMES: dict[str, str] = {}
for name in CANONICAL_MARKERS:
    flat = name.replace("_", "").lower()
    _NORMALISED_NAMES[flat] = name
    spaced = name.replace("_", " ").lower()
    _NORMALISED_NAMES[spaced] = name
    _NORMALISED_NAMES[name.lower()] = name
# Common semantic aliases the GM model invents by pattern-matching on the
# rest of the marker grammar (`UPDATE_NPC_PARAMS` / `UPDATE_PC_PARAMS` /
# `UPDATE_MEMORY` are real → it then makes up `UPDATE_OBJECTIVE` etc.).
# Map these to the closest canonical name so the marker still applies.
_SEMANTIC_ALIASES = {
    "update_objective": "SET_OBJECTIVE",
    "updateobjective": "SET_OBJECTIVE",
    "update objective": "SET_OBJECTIVE",
    "set_objectives": "SET_OBJECTIVE",
    "setobjectives": "SET_OBJECTIVE",
    "update_scene": "SET_SCENE",
    "updatescene": "SET_SCENE",
    "set_objective_text": "SET_OBJECTIVE",
}
_NORMALISED_NAMES.update(_SEMANTIC_ALIASES)


# ---------------------------------------------------------------------------
# Pass 1: strip markdown wrappers around the entire bracket
# ---------------------------------------------------------------------------

# Two wrapper shapes show up in practice:
#
#   `**[TAG ...]**`             — a single self-closing tag wrapped
#   `**[TAG]body[/TAG]**`       — paired tags + body wrapped together
#
# Plain `**` / `*` / `` ` `` / `_` runs of 1-3 chars are accepted on either
# side, the same run on both. We limit inner length so legitimate prose
# containing brackets isn't accidentally rewritten.
_WRAPPED_SINGLE_RE = re.compile(
    r"(\*{1,3}|`{1,3}|_{1,3})"
    r"(\[\s*/?\s*[A-Za-z][^\[\]\n]{0,500}\])"
    r"\1",
)
_WRAPPED_PAIR_RE = re.compile(
    r"(\*{1,3}|`{1,3}|_{1,3})"
    r"(\[\s*[A-Za-z][^\[\]\n]{0,200}\][^\[\]]{0,1500}?\[\s*/[^\[\]\n]{1,80}\])"
    r"\1",
    re.DOTALL,
)


def _strip_wrappers(text: str) -> str:
    """Repeatedly peel `**[TAG ...]**`, `*[/TAG]*`, ``` `[TAG]body[/TAG]` ```
    and similar. Iterates because nested wrappers (`***[TAG]***`) need
    multiple passes — each substitution eats the outermost wrapper only.

    Cap iterations: deep nesting is unusual and a runaway loop is worse
    than leaving a single weird wrapper in."""
    prev = None
    out = text
    for _ in range(5):
        if prev == out:
            break
        prev = out
        out = _WRAPPED_PAIR_RE.sub(r"\2", out)
        out = _WRAPPED_SINGLE_RE.sub(r"\2", out)
    return out


# ---------------------------------------------------------------------------
# Pass 2: normalise marker NAMES inside a tag (typos, spaces, missing _)
# ---------------------------------------------------------------------------

# Match a whole `[...]` tag. We then split the inner part into name + rest
# in code rather than in regex, because greedy character classes including
# space (needed for typos like `TAKE TIME`) collide with attribute syntax
# (`query="..."`) — the regex would happily eat past the marker name.
_TAG_RE = re.compile(r"\[(?P<inner>[^\[\]\n]{1,800})\]")
# Inside a tag, the name portion ends at the first attr boundary (`=`,
# whitespace-then-letter-followed-by-`=`, or a JSON `{`). We intentionally
# allow internal spaces in the name so that typos like `[TAKE TIME]` and
# `[UPDATE NPC PARAMS]` get a chance to be normalised before the boundary
# is computed.
_NAME_BOUNDARY_RE = re.compile(r"[\s\{]")


def _split_inner(inner: str) -> tuple[str, str, str]:
    """Return (slash, name, rest). `slash` is `/` or empty. `name` is the
    candidate marker name (may contain internal spaces). `rest` is the
    suffix (attrs / JSON body) verbatim including any leading whitespace."""
    s = inner.strip()
    slash = ""
    if s.startswith("/"):
        slash = "/"
        s = s[1:].lstrip()
    # Walk forward keeping letters / digits / underscore / space until we hit
    # a non-name char (= or { or end). Trim trailing whitespace — those
    # belong to the boundary, not the name.
    i = 0
    while i < len(s) and (s[i].isalnum() or s[i] == "_" or s[i] == " "):
        if s[i] == "=":
            break
        i += 1
    # If we stopped on `=`, back up to the last non-space char so `attr` of
    # `name attr="x"` doesn't get glued onto the name.
    name_part = s[:i].rstrip()
    rest = s[i:]
    if "=" in name_part and " " in name_part:
        # `name=value` with no leading attr name — defensive: cut at the
        # first space-followed-by-letter-then-`=` pattern.
        bits = name_part.split(" ", 1)
        if "=" in bits[1]:
            name_part = bits[0]
            rest = " " + bits[1] + rest
    return slash, name_part, rest


def _normalise_tag(match: re.Match) -> str:
    inner = match.group("inner")
    slash, name, rest = _split_inner(inner)
    if not name:
        return match.group(0)
    # Trim a trailing run of attr-name candidates: `[search_rules query]` was
    # parsed as name=`search_rules query` because we allow internal spaces.
    # Strip from the right while no canonical match.
    candidate = name
    canonical = None
    while candidate and canonical is None:
        canonical = _NORMALISED_NAMES.get(candidate.lower())
        if canonical is None:
            flat = re.sub(r"\s+", "", candidate).lower()
            canonical = _NORMALISED_NAMES.get(flat)
        if canonical is None and " " in candidate:
            candidate = candidate.rsplit(" ", 1)[0].rstrip()
        else:
            break
    if canonical is None:
        return match.group(0)
    # Restore the chunk we trimmed off the name back into rest.
    trimmed_off = name[len(candidate):]
    rest = trimmed_off + rest
    return f"[{slash}{canonical}{rest}]"


def _normalise_names(text: str) -> str:
    return _TAG_RE.sub(_normalise_tag, text)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def sanitize_markers(text: str) -> str:
    """Apply both passes to `text` and return the cleaned version. Idempotent
    — a text that's already clean comes through unchanged."""
    if not text:
        return text
    out = _strip_wrappers(text)
    out = _normalise_names(out)
    if out != text:
        logger.info("[marker_sanitize] cleaned %d → %d chars", len(text), len(out))
    return out
