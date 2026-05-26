"""Sanitize background planner observation metadata before storing it."""

from __future__ import annotations

import re
from typing import Any

from .common import to_plain_data


SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|password|token|secret|raw[_-]?prompt|raw[_-]?response|system[_-]?prompt|developer[_-]?prompt)",
    re.IGNORECASE,
)

MAX_STRING_VALUE = 800
MAX_LIST_ITEMS = 20
MAX_DICT_KEYS = 40


def sanitize_background_observation(value: Any) -> Any:
    """Drop private/debug-heavy fields from planner run summaries."""

    plain = to_plain_data(value)
    if isinstance(plain, dict):
        out: dict[str, Any] = {}
        for idx, (key, child) in enumerate(plain.items()):
            if idx >= MAX_DICT_KEYS:
                out["_truncated_keys"] = True
                break
            if SENSITIVE_KEY_RE.search(str(key)):
                continue
            out[str(key)] = sanitize_background_observation(child)
        return out
    if isinstance(plain, list):
        return [sanitize_background_observation(v) for v in plain[:MAX_LIST_ITEMS]]
    if isinstance(plain, str):
        return plain[:MAX_STRING_VALUE]
    return plain
