"""Source preprocessing — produce plain and line-numbered views.

Stage 1/2/3 consume the plain view (no line numbers) to encourage
whole-book concept formation. Stage 4/5/6 consume the line-numbered
view, optionally narrowed to line_hints ranges.

Line number format: [Lnnnnn] prefix, one line per source line, 1-based.
The prefix is padded to 6 digits so ranges stay easy to eyeball.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

try:
    from agents.trpg.rule_parser_v2.pass0_doc_nodes import get_full_markdown_for_files
except ModuleNotFoundError:
    get_full_markdown_for_files = None

logger = logging.getLogger("chatlab.trpg")


def _concat_markdown(markdown_map: Dict[str, str]) -> str:
    parts = [text for text in markdown_map.values() if text]
    return "\n\n".join(parts).strip()


def make_plain_view(markdown: str) -> str:
    """Return the source as-is, trimmed. No line numbers added."""
    return (markdown or "").rstrip()


def make_lined_view(markdown: str) -> Tuple[str, List[str]]:
    """Return (lined_text, raw_lines).

    lined_text: each source line prefixed with `[Lnnnnnn] `.
    raw_lines: the original lines (without prefix), used later for
    slicing narrow excerpts by line number range.
    """
    raw = (markdown or "").split("\n")
    out: List[str] = []
    for idx, line in enumerate(raw, start=1):
        out.append(f"[L{idx:06d}] {line}")
    return "\n".join(out), raw


async def load_book_views(
    file_ids: List[str],
    db,
) -> Tuple[str, str, List[str]]:
    """Load files from DB and build both views.

    Returns (plain_view, lined_view, raw_lines).
    Raises ValueError when the concatenated markdown is empty.
    """
    if get_full_markdown_for_files is None:
        raise ValueError(
            "AiChatTrpg does not provide ChatLab file_id markdown loading; "
            "pass normalized markdown directly instead.",
        )
    import asyncio

    markdown_map = await asyncio.to_thread(get_full_markdown_for_files, file_ids, db)
    full = _concat_markdown(markdown_map)
    if not full:
        raise ValueError("No content found in files")
    plain = make_plain_view(full)
    lined, raw_lines = make_lined_view(full)
    logger.info(
        "[V6] loaded book plain_chars=%d total_lines=%d files=%d",
        len(plain), len(raw_lines), len(file_ids),
    )
    return plain, lined, raw_lines
