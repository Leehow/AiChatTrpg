"""Pending-check attribute encoding helpers.

These helpers serialize the ``[pending_check ...]`` placeholder attributes
that ``render_pending_check`` emits when a CHECK should resolve later.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any


_PENDING_BASE_EXTRA_KEYS = (
    "actor",
    "actor_id",
    "npc_key",
    "check",
    "check_key",
    "param",
)

_PENDING_RESERVED_ATTRS = {
    "id",
    "engine",
    "roll_seed",
    "seed",
    "procedure_id",
    "skill",
    "value",
    "difficulty",
    "target",
    "pool",
    "bonus",
    "penalty",
    "reason",
    "roll",
    "auto",
    "actor",
    "actor_id",
    "npc_key",
    "check",
    "check_key",
    "param",
}

_SAFE_PENDING_EXTRA_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_SIMPLE_ATTR_VALUE_RE = re.compile(
    r"^[A-Za-z0-9_ .,:;+\-/@#|()\u4e00-\u9fff]{0,240}$"
)


def _quote_attr(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return '""'
    if any(ch in text for ch in ' \t"[]\n'):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _should_emit_pending_extra(key: str, value: Any) -> bool:
    text_key = str(key or "").strip()
    if not text_key or text_key.startswith("_"):
        return False
    if text_key in _PENDING_RESERVED_ATTRS:
        return False
    if not _SAFE_PENDING_EXTRA_KEY_RE.match(text_key):
        return False
    if value in (None, ""):
        return False
    return isinstance(value, (str, int, float, bool, list, dict))


def _encode_pending_extra_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return "json64:" + _b64_url_encode(body)
    text = str(value)
    if _SAFE_SIMPLE_ATTR_VALUE_RE.match(text):
        return text
    return "str64:" + _b64_url_encode(text)


def _b64_url_encode(text: str) -> str:
    encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")
