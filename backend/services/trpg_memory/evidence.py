"""Evidence-span helpers for memory proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .memory_models import EvidenceRole, SourceEvidence

_WORD_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")
_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+|\n+")


@dataclass(frozen=True)
class TextSource:
    text: str
    role: EvidenceRole


def make_source_evidence(
    *,
    memory_text: str,
    turn_id: str,
    sources: Iterable[TextSource],
    max_chars: int = 220,
) -> SourceEvidence | None:
    """Select a short transcript span that best supports ``memory_text``."""

    best: tuple[float, int, TextSource, str] | None = None
    needle_tokens = _tokens(memory_text)
    for source in sources:
        for span in _candidate_spans(source.text, max_chars=max_chars):
            score = _overlap_score(needle_tokens, _tokens(span))
            role_bias = 1 if source.role in {EvidenceRole.GM, EvidenceRole.STRUCTURED_EVENT} else 0
            item = (score, role_bias, source, span)
            if best is None or item[:2] > best[:2]:
                best = item
    if best is None:
        return None
    _, _, source, span = best
    if not span.strip():
        return None
    return SourceEvidence(text=span.strip()[:max_chars], role=source.role, source_turn_id=turn_id)


def evidence_overlap(memory_text: str, evidence_text: str) -> float:
    return _overlap_score(_tokens(memory_text), _tokens(evidence_text))


def _candidate_spans(text: str, *, max_chars: int) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    pieces = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()]
    if not pieces:
        pieces = [raw]
    out: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            out.append(piece)
        else:
            out.append(piece[:max_chars])
            mid = max(0, (len(piece) // 2) - (max_chars // 2))
            if mid > 0:
                out.append(piece[mid:mid + max_chars])
            out.append(piece[-max_chars:])
    return out


def _tokens(text: str) -> set[str]:
    value = str(text or "").casefold()
    words = {m.group(0) for m in _WORD_RE.finditer(value) if len(m.group(0)) >= 2}
    cjk_chars = {ch for ch in value if "\u4e00" <= ch <= "\u9fff"}
    return words | cjk_chars


def _overlap_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))
