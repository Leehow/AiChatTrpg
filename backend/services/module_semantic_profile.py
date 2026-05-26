"""Preflight and heading classification for module parsing."""

from __future__ import annotations

import re
from typing import Any

from services.module_semantic_shape import estimate_tokens

SKIP_TITLE_WORDS = {"目录", "table of contents", "contents"}


def doc_profile(markdown: str, title_hint: str = "") -> dict[str, Any]:
    dist = char_distribution(markdown[:100000])
    return {
        "title": clean_title_hint(title_hint) or guess_title(markdown, []),
        "language": classify_language(dist),
        "front_language": classify_language(char_distribution(markdown[:2500])),
        "total_tokens": estimate_tokens(markdown),
        "total_chars": len(markdown),
        "total_lines": len(markdown.splitlines()),
        "has_toc": bool(re.search(r"(目录|table of contents|contents)", markdown[:8000], re.I)),
        "char_distribution": dist,
        "excerpt": markdown[:800],
    }


def classify_title(title: str) -> str:
    text = title.lower()
    if is_bad_title(text):
        return "intro"
    if any(x in text for x in ("npc", "人物", "角色", "调查员", "怪物", "monster")):
        return "npc_list"
    if "附录" in text or "appendix" in text:
        if any(x in text for x in ("npc", "怪物", "monster", "道具", "item", "列表", "list")):
            return "appendix_list"
        if any(x in text for x in ("规则", "rule", "环境", "狩猎")):
            return "appendix_rules"
        return "appendix_others"
    if any(x in text for x in ("handout", "手记", "信件", "文档")):
        return "handout"
    if any(x in text for x in ("rule", "规则", "spell", "法术", "技能")):
        return "rules"
    if any(x in text for x in ("时间线", "timeline")):
        return "timeline"
    if any(x in text for x in ("map", "地图")):
        return "map"
    if any(x in text for x in ("location", "地点", "场景", "地图", "镇", "城市", "基地", "矿场", "矿井", "洞", "公路", "城", "村")):
        return "location"
    if any(x in text for x in ("intro", "开幕", "背景", "概述", "hook", "导入", "警告", "模组信息", "守密人", "运行")):
        return "intro"
    if any(x in text for x in ("mission", "任务", "operation", "quest")):
        return "mission"
    if any(x in text for x in ("chapter", "章节", "幕", "序幕")):
        return "chapter"
    if any(x in text for x in ("ending", "结局", "结尾")):
        return "chapter"
    return "other"


def guess_title(markdown: str, outline: list[dict[str, Any]]) -> str:
    for item in outline:
        title = str(item.get("title") or "").strip()
        if title and not is_bad_title(title):
            return title
    for line in markdown.splitlines()[:30]:
        clean = line.strip(" #\t")
        if clean and not is_bad_title(clean):
            return clean[:80]
    return "Untitled module"


def major_outline(outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not outline:
        return outline
    top = min(_int(item.get("level"), 1) for item in outline if _int(item.get("level"), 1) > 0)
    major = [item for item in outline if _int(item.get("level"), 1) == top]
    if len(major) >= 4:
        return major
    return [item for item in outline if _int(item.get("level"), 1) <= min(2, top + 1)]


def clean_title_hint(title: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]+$", "", str(title or "").strip())[:120]


def is_bad_title(title: str) -> bool:
    return str(title or "").strip().lower() in SKIP_TITLE_WORDS


def char_distribution(text: str) -> dict[str, int]:
    return {
        "hanzi": len(re.findall(r"[\u4e00-\u9fff]", text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", text)),
        "hangul": len(re.findall(r"[\uac00-\ud7af]", text)),
        "alpha": len(re.findall(r"[A-Za-z]", text)),
        "total_meaningful": len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z]", text)),
    }


def classify_language(dist: dict[str, int]) -> str:
    total = max(1, dist.get("total_meaningful", 0))
    if dist.get("hanzi", 0) / total > 0.25:
        return "zh"
    if dist.get("kana", 0) / total > 0.1:
        return "ja"
    if dist.get("hangul", 0) / total > 0.1:
        return "ko"
    if dist.get("alpha", 0) / total > 0.5:
        return "en"
    return "mixed"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
