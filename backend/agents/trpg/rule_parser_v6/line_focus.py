"""Narrow-excerpt slicing for Stage 4-6 extraction.

Given line_hints and source_cues from the discovery manifest, slice
a focused excerpt out of the line-numbered book view. Falls back
gracefully when hints are missing, invalid, or too sparse.

Strategy:
1. If line_hints provided, merge/pad ranges and concatenate slices.
2. If result is too small or empty, append cue-keyword neighborhoods
   (±CUE_CONTEXT lines around every raw-line match of a source_cue).
3. If still empty, return the full lined view.
4. Cap total characters at `max_chars` — oldest hint wins.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger("chatlab.trpg")

# Padding added above/below each explicit line_hint range.
HINT_PAD = 50
# Lines of context around each cue-keyword match.
CUE_CONTEXT = 30
# If the merged hint slice has fewer than this many lines, also pull
# in cue neighborhoods to round out the excerpt.
MIN_LINES_BEFORE_CUE_FALLBACK = 40
# Default cap on excerpt length (char count, not tokens). Tuned so
# even a big 3-hint slice fits comfortably in a long-context window
# alongside resident core and the descriptor.
DEFAULT_MAX_CHARS = 400_000


def _coerce_ranges(line_hints: Any) -> List[Tuple[int, int]]:
    """Parse and sanitize the line_hints list.

    Accepts [[start, end], ...] with 1-based inclusive bounds. Drops
    entries that are non-numeric, zero/negative, or where start > end.
    """
    out: List[Tuple[int, int]] = []
    if not isinstance(line_hints, list):
        return out
    for entry in line_hints:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            try:
                start = int(entry[0])
                end = int(entry[1])
            except (TypeError, ValueError):
                continue
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start
            out.append((start, end))
    return out


def _pad_and_merge(
    ranges: Sequence[Tuple[int, int]],
    total_lines: int,
    pad: int,
) -> List[Tuple[int, int]]:
    """Pad each range then merge overlaps. 1-based inclusive."""
    if not ranges:
        return []
    padded: List[Tuple[int, int]] = []
    for start, end in ranges:
        lo = max(1, start - pad)
        hi = min(total_lines, end + pad)
        if lo <= hi:
            padded.append((lo, hi))
    padded.sort()
    merged: List[Tuple[int, int]] = []
    for lo, hi in padded:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _cue_ranges(
    raw_lines: Sequence[str],
    source_cues: Sequence[str],
    context: int,
) -> List[Tuple[int, int]]:
    """Find line ranges around every cue keyword hit (case-insensitive)."""
    if not source_cues or not raw_lines:
        return []
    # Sanitize cues, drop empties and very short tokens that would match
    # too broadly.
    patterns: List[re.Pattern] = []
    for cue in source_cues:
        term = str(cue or "").strip()
        if len(term) < 3:
            continue
        patterns.append(re.compile(re.escape(term), re.IGNORECASE))
    if not patterns:
        return []
    ranges: List[Tuple[int, int]] = []
    total = len(raw_lines)
    for idx, line in enumerate(raw_lines, start=1):
        for pat in patterns:
            if pat.search(line):
                lo = max(1, idx - context)
                hi = min(total, idx + context)
                ranges.append((lo, hi))
                break
    return ranges


def _render_slices(
    lined_view_lines: Sequence[str],
    ranges: Sequence[Tuple[int, int]],
) -> str:
    """Concatenate slices with a visible separator line between chunks."""
    chunks: List[str] = []
    for start, end in ranges:
        # Convert 1-based inclusive to 0-based slice bounds.
        lo = max(0, start - 1)
        hi = min(len(lined_view_lines), end)
        if lo >= hi:
            continue
        chunk = "\n".join(lined_view_lines[lo:hi])
        chunks.append(chunk)
    if not chunks:
        return ""
    sep = "\n\n[...omitted...]\n\n"
    return sep.join(chunks)


def build_narrow_excerpt(
    *,
    lined_view: str,
    raw_lines: Sequence[str],
    line_hints: Any,
    source_cues: Sequence[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Tuple[str, bool, Dict[str, Any]]:
    """Build a narrow line-numbered excerpt focused on target ranges.

    Returns (excerpt, narrowed, stats).
    - excerpt: the lined-view slices (or the full lined view as fallback)
    - narrowed: True when any hint / cue actually narrowed the excerpt
    - stats: {hint_ranges, cue_ranges, merged_ranges, char_count}
    """
    total_lines = len(raw_lines)
    lined_lines = lined_view.split("\n") if lined_view else []
    cues = list(source_cues or [])
    hint_ranges = _coerce_ranges(line_hints)

    merged = _pad_and_merge(hint_ranges, total_lines, HINT_PAD)
    hint_line_count = sum(end - start + 1 for start, end in merged)

    cue_ranges: List[Tuple[int, int]] = []
    if hint_line_count < MIN_LINES_BEFORE_CUE_FALLBACK:
        cue_ranges = _cue_ranges(raw_lines, cues, CUE_CONTEXT)
        merged = _pad_and_merge(list(merged) + cue_ranges, total_lines, 0)

    # If still empty, fall back to the full lined view.
    if not merged:
        excerpt = lined_view
        narrowed = False
    else:
        excerpt = _render_slices(lined_lines, merged)
        narrowed = bool(merged)
        if not excerpt:
            excerpt = lined_view
            narrowed = False

    # Enforce max_chars by trimming trailing content.
    if excerpt and len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n\n[...truncated by max_chars cap...]"

    stats = {
        "hint_ranges": [list(r) for r in hint_ranges],
        "cue_ranges": [list(r) for r in cue_ranges],
        "merged_ranges": [list(r) for r in merged],
        "char_count": len(excerpt),
    }
    logger.info(
        "[V6] narrow excerpt hints=%d cues=%d merged=%d chars=%d narrowed=%s",
        len(hint_ranges), len(cue_ranges), len(merged),
        len(excerpt), narrowed,
    )
    return excerpt, narrowed, stats
