"""TTS voice assignment for NPC rosters.

Picks compatible voices for each NPC from the pool registered for the
configured TTS provider. ``_assign_missing_voices`` is the entry point
used by ``ensure_npc_assets`` and by routes that need to retro-fit
voices when a roster predates the auto-assign logic.
"""

from __future__ import annotations

import hashlib
from typing import Any

from services.trpg_npc.assets_voice_pools import (
    _gender_text,
    _is_female,
    _tts_provider_for_model,
    _voice_pools,
)


def _assign_missing_voices(npcs: list[Any], tts_model: str) -> int:
    provider = _tts_provider_for_model(tts_model)
    used: set[str] = set()
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        voice = _effective_voice(npc, provider, tts_model)
        if voice:
            used.add(voice)

    changed = 0
    for npc in sorted(
        [n for n in npcs if isinstance(n, dict)],
        key=lambda n: (str(n.get("key") or ""), str(n.get("name") or "")),
    ):
        voice = _effective_voice(npc, provider, tts_model)
        if voice:
            npc["active_tts_voice"] = voice
            npc["tts_voice_model"] = tts_model
            npc["tts_voice_provider"] = provider
            continue

        chosen = _keyword_voice(npc, tts_model, used) or _stable_voice(
            npc, tts_model, used,
        )
        if not chosen:
            continue

        primary = str(npc.get("tts_voice") or "").strip()
        if not primary:
            npc["tts_voice"] = chosen
        else:
            overrides = npc.get("tts_voice_overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            overrides[provider] = chosen
            npc["tts_voice_overrides"] = overrides
        npc["active_tts_voice"] = chosen
        npc["tts_voice_model"] = tts_model
        npc["tts_voice_provider"] = provider
        used.add(chosen)
        changed += 1
    return changed


def _effective_voice(npc: dict[str, Any], provider: str, tts_model: str) -> str:
    overrides = npc.get("tts_voice_overrides")
    if isinstance(overrides, dict):
        override = str(overrides.get(provider) or "").strip()
        if _voice_compatible(override, tts_model):
            return override
    primary = str(npc.get("tts_voice") or "").strip()
    if _voice_compatible(primary, tts_model):
        return primary
    return ""


def _voice_compatible(voice: str, tts_model: str) -> bool:
    if not voice:
        return False
    male, female = _voice_pools(tts_model)
    return voice in {*male, *female}


def _stable_voice(npc: dict[str, Any], tts_model: str, used: set[str]) -> str:
    male, female = _voice_pools(tts_model)
    pool = female if _is_female(npc) else male
    if not pool:
        return ""
    seed = "|".join([
        _tts_provider_for_model(tts_model),
        str(npc.get("key") or ""),
        str(npc.get("name") or ""),
        _gender_text(npc),
        str(npc.get("summary") or npc.get("description") or "")[:120],
    ])
    start = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(pool)
    for offset in range(len(pool)):
        candidate = pool[(start + offset) % len(pool)]
        if candidate not in used:
            return candidate
    return pool[start]


def _keyword_voice(npc: dict[str, Any], tts_model: str, used: set[str]) -> str:
    provider = _tts_provider_for_model(tts_model)
    female = _is_female(npc)
    text = _voice_match_text(npc)
    candidates: list[str] = []

    if provider == "gemini":
        if female:
            if _has_any(text, "女王", "指挥", "军官", "权威", "坚定", "leader", "commander"):
                candidates += ["Kore", "Gacrux", "Pulcherrima"]
            if _has_any(text, "温柔", "护士", "治疗", "母亲", "安慰", "soft", "healer"):
                candidates += ["Achernar", "Sulafat", "Vindemiatrix"]
            if _has_any(text, "少女", "年轻", "活泼", "乐观", "学徒", "young", "girl"):
                candidates += ["Leda", "Zephyr", "Laomedeia"]
            candidates += ["Schedar", "Erinome", "Callirrhoe"]
        else:
            if _has_any(text, "反派", "佣兵", "老兵", "沙哑", "威胁", "villain", "mercenary"):
                candidates += ["Algenib", "Fenrir", "Orus"]
            if _has_any(text, "军官", "守卫", "队长", "命令", "权威", "guard", "officer"):
                candidates += ["Alnilam", "Orus", "Rasalgethi"]
            if _has_any(text, "学者", "教授", "医生", "智者", "老人", "old", "scholar"):
                candidates += ["Sadaltager", "Rasalgethi", "Charon"]
            if _has_any(text, "少年", "年轻", "活泼", "伙伴", "young", "boy"):
                candidates += ["Puck", "Achird", "Sadachbia"]
            candidates += ["Charon", "Umbriel", "Achird"]
    elif provider == "minimax":
        if female:
            if _has_any(text, "女王", "高冷", "威严", "权威", "queen", "command"):
                candidates += ["chatlab-rp-8009b953", "chatlab-rp-2e2d59ff"]
            if _has_any(text, "阴狠", "恶毒", "反派", "villain", "sinister"):
                candidates += ["chatlab-rp-7709ba40"]
            if _has_any(text, "老人", "老年", "慈祥", "old", "elder"):
                candidates += ["chatlab-rp-0e958089", "chatlab-rp-53f2d35b"]
            if _has_any(text, "小孩", "女孩", "萝莉", "child", "girl"):
                candidates += ["chatlab-rp-bcc18060", "chatlab-rp-40365004"]
            if _has_any(text, "知性", "秘书", "医生", "白领", "teacher", "doctor"):
                candidates += ["chatlab-rp-6922d8df", "chatlab-rp-7413f058"]
            candidates += ["chatlab-rp-296ef640", "female-yujie", "female-chengshu"]
        else:
            if _has_any(text, "反派", "阴险", "威胁", "villain", "sinister"):
                candidates += ["chatlab-rp-26d59fc5"]
            if _has_any(text, "军官", "统帅", "队长", "命令", "officer", "commander"):
                candidates += ["chatlab-rp-acbd6a14", "chatlab-rp-10db0dd8"]
            if _has_any(text, "老人", "老年", "大爷", "沙哑", "old", "elder"):
                candidates += ["chatlab-rp-5031b687", "chatlab-rp-9f67ee96", "chatlab-rp-6cf303eb"]
            if _has_any(text, "僧", "牧师", "祭司", "monk", "priest"):
                candidates += ["chatlab-rp-20e34cdd"]
            if _has_any(text, "少年", "年轻", "男孩", "young", "boy"):
                candidates += ["chatlab-rp-fe6d404d", "chatlab-rp-1a0e260b"]
            if _has_any(text, "书生", "学者", "温润", "scholar", "gentle"):
                candidates += ["chatlab-rp-3745067b", "chatlab-rp-e97f60f9"]
            candidates += ["male-qn-jingying", "male-qn-qingse", "male-qn-badao"]
    else:
        if female:
            if _has_any(text, "成熟", "知性", "温柔", "医生", "老师", "mature", "teacher"):
                candidates += ["Serena"]
            if _has_any(text, "少女", "年轻", "活泼", "girl", "young"):
                candidates += ["Cherry", "Vivian"]
            candidates += ["Serena", "Cherry", "Vivian"]
        else:
            if _has_any(text, "幽默", "方言", "市井", "humor"):
                candidates += ["Eric"]
            if _has_any(text, "美式", "外国", "english", "american"):
                candidates += ["Aiden", "Ryan"]
            candidates += ["Dylan", "Aiden", "Eric", "Ryan"]

    for voice in candidates:
        if voice not in used and _voice_compatible(voice, tts_model):
            return voice
    for voice in candidates:
        if _voice_compatible(voice, tts_model):
            return voice
    return ""


def _voice_match_text(npc: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "name",
        "gender",
        "age",
        "role",
        "title",
        "summary",
        "description",
        "appearance",
        "personality",
        "voice_hint",
        "portrait_prompt",
    ):
        value = npc.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts).lower()


def _has_any(text: str, *needles: str) -> bool:
    return any(needle.lower() in text for needle in needles)
