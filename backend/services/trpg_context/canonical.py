"""Stable serialization helpers.

Prompt caching is usually prefix-sensitive, so text generation must be
byte-stable for unchanged blocks. Keep all dynamic values out of prefix blocks.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .models import ContextBlock


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for prompt and hash generation."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_content(content: Mapping[str, Any] | str) -> str:
    if isinstance(content, str):
        # Normalize line endings but do not strip internal content.
        return content.replace("\r\n", "\n").replace("\r", "\n").strip()
    return canonical_json(content)


def render_block(block: ContextBlock) -> str:
    """Render a ContextBlock using a stable, explicit envelope.

    The envelope intentionally includes block_id/version/kind. This helps the
    model understand provenance and helps logs diagnose cache-busting changes.
    """
    content = normalize_content(block.content)
    header = (
        f"<context_block id=\"{block.block_id}\" "
        f"version=\"{block.version}\" "
        f"kind=\"{block.kind.value}\" "
        f"visibility=\"{block.visibility.value}\" "
        f"stability=\"{block.stability.value}\">"
    )
    footer = "</context_block>"
    return f"{header}\n<title>{block.title}</title>\n{content}\n{footer}"


def render_blocks(blocks: list[ContextBlock] | tuple[ContextBlock, ...]) -> str:
    return "\n\n".join(render_block(block) for block in blocks)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate for budgeting.

    Replace with provider tokenizer where available. This approximation is safe
    enough for ordering and rough budget trimming.
    """
    if not text:
        return 0
    # Mixed Chinese/English RPG text tends to be denser than English-only text.
    return max(1, int(len(text) / 2.8))
