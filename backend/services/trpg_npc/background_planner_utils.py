"""Small coercion / parsing helpers shared by background_planner modules."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.trpg.llm_json import extract_json_object
from services.trpg_npc.models import ActionType


logger = logging.getLogger("chatrpg.trpg_npc.background_planner")


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return extract_json_object(text)
    except Exception:
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            logger.warning("[npc_background_planner] could not parse JSON: %.200s", text)
            return {}


def _action_type(value: Any) -> ActionType:
    raw = str(value or "").strip().upper()
    try:
        return ActionType(raw)
    except Exception:
        return ActionType.SAY


def _short_text(value: Any, *, fallback: str = "", max_len: int) -> str:
    text = str(value or fallback or "").strip()
    return text[:max_len]


def _list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
