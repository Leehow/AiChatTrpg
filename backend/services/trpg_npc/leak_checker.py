"""Deterministic secret leak checker for generated NPC/GM text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from services.trpg_memory.memory_models import MemoryItem


@dataclass(frozen=True)
class LeakWarning:
    memory_id: str
    severity: str
    reason: str
    matched_terms: tuple[str, ...]


class LeakChecker:
    def __init__(self, *, token_overlap_threshold: float = 0.72, min_secret_tokens: int = 4) -> None:
        self.token_overlap_threshold = token_overlap_threshold
        self.min_secret_tokens = min_secret_tokens

    def check(self, *, generated_text: str, forbidden_memories: Iterable[MemoryItem]) -> tuple[LeakWarning, ...]:
        normalized_output = self._normalize(generated_text)
        output_tokens = set(self._tokens(generated_text))
        warnings: list[LeakWarning] = []
        for memory in forbidden_memories:
            secret = self._normalize(memory.text)
            if not secret:
                continue
            if secret in normalized_output:
                warnings.append(
                    LeakWarning(memory_id=memory.memory_id, severity="error", reason="exact secret text appeared in generated output", matched_terms=(memory.text,))
                )
                continue
            secret_tokens = set(self._tokens(memory.text))
            if len(secret_tokens) < self.min_secret_tokens:
                continue
            overlap = secret_tokens.intersection(output_tokens)
            score = len(overlap) / max(len(secret_tokens), 1)
            if score >= self.token_overlap_threshold:
                warnings.append(
                    LeakWarning(
                        memory_id=memory.memory_id,
                        severity="warning",
                        reason=f"generated output overlaps forbidden memory tokens ({score:.2f})",
                        matched_terms=tuple(sorted(overlap)),
                    )
                )
        return tuple(warnings)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()

    def _tokens(self, text: str) -> list[str]:
        # Keep CJK characters as individual tokens and Latin words as words.
        return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+", text.casefold())
