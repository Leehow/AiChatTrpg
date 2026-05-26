"""Cheap memory salience retrieval for foreground NPC liveness."""

from __future__ import annotations

import re
from typing import Any

from .common import clamp, get_value, short_text, stable_list, text_blob
from .models import SalientMemory


def retrieve_salient_memories(
    npc: Any,
    *,
    player_text: str,
    recent_events: list[Any] | None = None,
    limit: int = 3,
) -> list[SalientMemory]:
    memories = get_value(npc, "memories_v2") or get_value(npc, "memories") or []
    if not isinstance(memories, list):
        return []

    query_tags = _query_tags(player_text, recent_events or [])
    query_text = text_blob(player_text, [get_value(ev, "content") for ev in recent_events or []])
    scored: list[tuple[float, SalientMemory]] = []
    for index, raw in enumerate(memories):
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or raw.get("summary") or "").strip()
        if not content:
            continue
        tags = [str(tag) for tag in stable_list(raw.get("tags"))]
        importance = clamp(raw.get("importance", 0.4))
        turn_id = _int(raw.get("turn_id"), index)
        tag_overlap = len(set(tags).intersection(query_tags)) * 0.22
        text_overlap = _text_overlap(content, query_text) * 0.18
        recency = min(max(turn_id, 0) / 1000.0, 0.12)
        score = importance * 0.55 + tag_overlap + text_overlap + recency
        if score < 0.18:
            continue
        influence = _influence_from_memory(content, tags)
        scored.append((score, SalientMemory(
            memory_id=str(raw.get("memory_id") or f"memory_{index}"),
            content=short_text(content, max_len=240),
            relevance=round(score, 4),
            influence=influence,
            tags=tags[:6],
        )))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _score, item in scored[: max(0, limit)]]


def _query_tags(player_text: str, events: list[Any]) -> set[str]:
    text = text_blob(player_text, [get_value(ev, "type") for ev in events], [get_value(get_value(ev, "payload", {}), "topic_tags") for ev in events])
    tags: set[str] = set()
    patterns = {
        "threat": r"威胁|恐吓|攻击|attack|threat",
        "help": r"保护|帮助|救|protect|help|save",
        "secret_topic": r"秘密|邪教|主谋|幕后|secret|cult|leader",
        "symbol": r"符号|徽记|图案|symbol|sigil",
        "missing_person": r"失踪|missing",
        "deal": r"交易|贿赂|报酬|deal|bribe|reward",
    }
    for tag, pattern in patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            tags.add(tag)
    return tags


def _text_overlap(content: str, query_text: str) -> float:
    if not content or not query_text:
        return 0.0
    content_chars = {c for c in content.lower() if c.strip()}
    query_chars = {c for c in query_text.lower() if c.strip()}
    if not content_chars or not query_chars:
        return 0.0
    return min(len(content_chars.intersection(query_chars)) / max(len(query_chars), 1), 1.0)


def _influence_from_memory(content: str, tags: list[str]) -> str:
    blob = text_blob(content, tags)
    if any(token in blob for token in ["救", "保护", "help", "save", "protect"]):
        return "对玩家的语气会软化，但仍会评估风险。"
    if any(token in blob for token in ["威胁", "攻击", "threat", "attack"]):
        return "更戒备，回答更短，更容易要求距离或证据。"
    if any(token in blob for token in ["撒谎", "背叛", "lie", "betray"]):
        return "会要求玩家给出证据，不轻易相信承诺。"
    if any(token in blob for token in ["秘密", "邪教", "symbol", "sigil", "cult"]):
        return "会避开公开回答，倾向转入私下或给模糊提示。"
    return "作为微妙背景影响语气和肢体反应。"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
