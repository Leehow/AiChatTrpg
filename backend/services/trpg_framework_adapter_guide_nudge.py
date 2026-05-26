"""Guide-mode dialogue nudges for the chatrpg framework adapter.

Reads the player's recent setup-chat history + current message to decide
whether (and how) to inject a multicultural naming / background variety hint.
The goal is to avoid homogeneous names when the player hasn't committed to
one yet — without overriding a name they already chose.

Split out of `trpg_framework_adapter.py` purely for file-size hygiene; this
module is private to the adapter.
"""

from __future__ import annotations

import re

from agents.trpg.framework.models import Message


def _build_guide_name_variety_text(
    *,
    message: str,
    recent_history: list[Message],
    target_language: str = "",
) -> str:
    from agents.trpg.name_culture_pool import (
        build_batch_culture_rules,
        build_single_culture_rule,
        build_uncommitted_name_guidance,
        make_generation_nonce,
    )

    current = message or ""
    user_text = _joined_user_text(recent_history, current)
    if _player_has_manual_name(user_text):
        return ""

    current_lower = current.lower()
    wants_batch = _wants_multiple_character_candidates(current, current_lower)
    wants_ai_name = _wants_ai_name_or_character_fill(current, current_lower)
    has_guide_context = bool((current or user_text).strip())
    if not (wants_batch or wants_ai_name or has_guide_context):
        return ""

    parts = [
        "## Guide Dialogue Nudge: Character Variety\n"
        f"variation_seed: {make_generation_nonce()}\n"
        "Use this only during setup dialogue. It is not a final JSON-card rule. "
        "Preserve any name, culture, homeland, ancestry, or background the "
        "player has already specified. The goal is to avoid homogeneous names "
        "and backstories when the player leaves those choices open."
    ]
    language = target_language or "the player's selected language"
    if wants_batch:
        parts.append(build_batch_culture_rules(3, target_language=language))
    elif wants_ai_name:
        parts.append(build_single_culture_rule(target_language=language))
    else:
        parts.append(build_uncommitted_name_guidance(target_language=language))
    return "\n\n".join(parts)


def _joined_user_text(recent_history: list[Message], current: str) -> str:
    parts = [
        str(m.content or "")
        for m in recent_history[-8:]
        if getattr(m, "role", "") == "user" and str(m.content or "").strip()
    ]
    if current and (not parts or parts[-1] != current):
        parts.append(current)
    return "\n".join(parts)


def _player_has_manual_name(user_text: str) -> bool:
    if not user_text:
        return False
    patterns = (
        r"(?:名字|姓名)\s*(?:是|叫|叫做|[:：])\s*[A-Za-z\u4e00-\u9fff][^，。；;,.!?\n]{1,40}",
        r"(?:我|他|她|ta|TA|角色|这个人|这人)\s*(?:叫|名叫|叫做)\s*[A-Za-z\u4e00-\u9fff][^，。；;,.!?\n]{1,40}",
        r"\b(?:my|his|her|their|the character's)\s+name\s+is\s+[A-Z][A-Za-z' -]{1,50}",
        r"\b(?:called|named|goes by)\s+[A-Z][A-Za-z' -]{1,50}",
    )
    question_markers = ("叫什么", "什么名字", "what name", "which name")
    for pattern in patterns:
        match = re.search(pattern, user_text, flags=re.IGNORECASE)
        if not match:
            continue
        span = user_text[max(0, match.start() - 8):match.end() + 8].lower()
        if any(marker in span for marker in question_markers):
            continue
        return True
    return False


def _wants_multiple_character_candidates(current: str, current_lower: str) -> bool:
    return any(
        kw in current
        for kw in (
            "三套", "三个", "3个", "3 个", "3套", "3 套",
            "多个角色", "几个人物", "候选角色", "几个候选",
        )
    ) or any(
        kw in current_lower
        for kw in (
            "multiple characters", "three characters", "character candidates",
            "several characters", "a few characters",
        )
    )


def _wants_ai_name_or_character_fill(current: str, current_lower: str) -> bool:
    return (
        "[AUTO_CREATE_CHARACTER]" in current
        or "[QUICK_CREATE_CHARACTER]" in current
        or any(
            kw in current
            for kw in (
                "自动", "随机", "帮我填", "帮我补全", "帮我生成",
                "直接帮我", "你来定", "你帮我定", "懒得想", "生成完整",
                "完整角色", "推荐名字", "起个名字", "取个名字",
                "想个名字", "名字你定", "没有名字",
            )
        )
        or bool(re.search(r"(帮我|给我|替我).{0,8}(起|取|想).{0,4}名字", current))
        or any(
            kw in current_lower
            for kw in (
                "auto create", "auto-create", "auto generate", "auto-generate",
                "generate a character", "make me a character",
                "create a character for me", "fill the character",
                "fill the sheet", "recommend a name", "suggest a name",
                "you decide the name",
            )
        )
    )
