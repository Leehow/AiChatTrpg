"""Parse `<<<FILE:filename>>> ... <<<END_FILE>>>` output blocks.

All v6 prompts use this exact envelope for artifact output. The
parser tolerates:
- leading / trailing explanation text (stripped)
- multiple file blocks in one response (kept in order)
- CRLF line endings
- stray whitespace around delimiters

It does NOT tolerate:
- mismatched open/close pairs (raises)
- nested blocks (a new `<<<FILE:` inside a block terminates the
  outer block as a malformed output and raises)
"""

from __future__ import annotations

import re
from typing import Dict, List


_OPEN_RE = re.compile(r"<<<FILE:([^>\r\n]+)>>>")
_CLOSE = "<<<END_FILE>>>"


class FileBlockParseError(ValueError):
    """Raised when a response cannot be parsed into file blocks."""


def parse_file_blocks(text: str) -> List[Dict[str, str]]:
    """Return a list of {filename, content} dicts in order of appearance.

    Empty or whitespace-only inputs return [].
    Raises FileBlockParseError when delimiters are malformed.
    """
    if not text or not text.strip():
        return []

    # Normalize newlines for simpler matching.
    body = text.replace("\r\n", "\n").replace("\r", "\n")

    out: List[Dict[str, str]] = []
    pos = 0
    while True:
        open_match = _OPEN_RE.search(body, pos)
        if not open_match:
            break
        filename = open_match.group(1).strip()
        if not filename:
            raise FileBlockParseError(
                f"Empty filename in FILE block at offset {open_match.start()}",
            )
        content_start = open_match.end()
        # Skip one leading newline after the opener, if any.
        if content_start < len(body) and body[content_start] == "\n":
            content_start += 1
        close_idx = body.find(_CLOSE, content_start)
        if close_idx < 0:
            raise FileBlockParseError(
                f"Missing <<<END_FILE>>> after <<<FILE:{filename}>>>",
            )
        # Reject nested FILE opens within the current block.
        nested = _OPEN_RE.search(body, content_start)
        if nested and nested.start() < close_idx:
            raise FileBlockParseError(
                f"Nested <<<FILE:...>>> inside block '{filename}' — "
                "looks like a malformed response",
            )
        raw_content = body[content_start:close_idx]
        # Trim one trailing newline that precedes the closer.
        if raw_content.endswith("\n"):
            raw_content = raw_content[:-1]
        out.append({"filename": filename, "content": raw_content})
        pos = close_idx + len(_CLOSE)
    return out


def find_block(blocks: List[Dict[str, str]], filename: str) -> str | None:
    """Return the content of the first block whose filename matches exactly."""
    for block in blocks:
        if block.get("filename") == filename:
            return block.get("content")
    return None


def require_block(blocks: List[Dict[str, str]], filename: str) -> str:
    """Like find_block but raises FileBlockParseError on miss."""
    content = find_block(blocks, filename)
    if content is None:
        available = ", ".join(b.get("filename", "?") for b in blocks) or "(none)"
        raise FileBlockParseError(
            f"Expected <<<FILE:{filename}>>> block — got: {available}",
        )
    return content
