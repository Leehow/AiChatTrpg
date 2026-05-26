"""Voice pool catalogs and TTS provider routing for NPC assets.

Owns the dialect lists for each supported TTS backend, the gender
detection helpers, and the small ``_tts_provider_for_model`` /
``_voice_pools`` routers that voice-assignment logic depends on.
"""

from __future__ import annotations

import re
from typing import Any

MALE_VOICES = ["Dylan", "Eric", "Ryan", "Aiden"]
FEMALE_VOICES = ["Cherry", "Vivian", "Serena"]

MINIMAX_MALE = [
    "chatlab-rp-25925d1f",
    "chatlab-rp-26d59fc5",
    "chatlab-rp-e97f60f9",
    "chatlab-rp-3745067b",
    "chatlab-rp-fe6d404d",
    "chatlab-rp-acbd6a14",
    "chatlab-rp-5031b687",
    "chatlab-rp-20e34cdd",
    "chatlab-rp-1a0e260b",
    "chatlab-rp-10db0dd8",
    "chatlab-rp-7baeb7cb",
    "chatlab-rp-9f67ee96",
    "chatlab-rp-6cf303eb",
    "male-qn-qingse",
    "male-qn-jingying",
    "male-qn-badao",
    "male-qn-daxuesheng",
    "presenter_male",
    "audiobook_male_1",
    "Young_Knight",
    "Deep_Voice_Man",
]
MINIMAX_FEMALE = [
    "chatlab-rp-8009b953",
    "chatlab-rp-6922d8df",
    "chatlab-rp-fee66a95",
    "chatlab-rp-296ef640",
    "chatlab-rp-40365004",
    "chatlab-rp-7a1af54b",
    "chatlab-rp-7413f058",
    "chatlab-rp-bcc18060",
    "chatlab-rp-2e2d59ff",
    "chatlab-rp-7709ba40",
    "chatlab-rp-0e958089",
    "chatlab-rp-53f2d35b",
    "female-shaonv",
    "female-yujie",
    "female-chengshu",
    "female-tianmei",
    "English_expressive_narrator",
    "presenter_female",
    "audiobook_female_1",
    "Calm_Woman",
    "Sweet_Girl",
]

GEMINI_MALE = [
    "Puck",
    "Charon",
    "Fenrir",
    "Orus",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Algenib",
    "Rasalgethi",
    "Alnilam",
    "Achird",
    "Zubenelgenubi",
    "Sadachbia",
    "Sadaltager",
]
GEMINI_FEMALE = [
    "Zephyr",
    "Kore",
    "Leda",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Despina",
    "Erinome",
    "Laomedeia",
    "Achernar",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Vindemiatrix",
    "Sulafat",
]

_FEMALE_HINT_RE = re.compile(
    r"女|女性|女人|女子|女孩|少女|女士|夫人|小姐|母亲|妈妈|奶奶|阿姨|"
    r"\bfemale\b|\bwoman\b|\bgirl\b|\blady\b|\bmother\b",
    re.I,
)
_MALE_HINT_RE = re.compile(
    r"男|男性|男人|男子|男孩|少年|先生|父亲|爸爸|爷爷|大叔|"
    r"\bmale\b|\bman\b|\bboy\b|\bgentleman\b|\bfather\b",
    re.I,
)


def _tts_provider_for_model(model: str | None) -> str:
    m = (model or "").lower()
    if "gemini" in m and "tts" in m:
        return "gemini"
    if "minimax" in m or "speech-2" in m:
        return "minimax"
    return "dashscope"


def _voice_pools(model: str | None) -> tuple[list[str], list[str]]:
    provider = _tts_provider_for_model(model)
    if provider == "gemini":
        return GEMINI_MALE, GEMINI_FEMALE
    if provider == "minimax":
        return MINIMAX_MALE, MINIMAX_FEMALE
    return MALE_VOICES, FEMALE_VOICES


def _gender_text(npc: dict[str, Any]) -> str:
    raw = npc.get("gender")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    for wrapper in ("identity", "basic", "profile", "bio", "info"):
        nested = npc.get(wrapper)
        if isinstance(nested, dict):
            raw = nested.get("gender")
            if isinstance(raw, str) and raw.strip():
                return raw.strip().lower()
    return ""


def _is_female(npc: dict[str, Any]) -> bool:
    text = _gender_text(npc)
    if not text:
        probe = " ".join(
            str(npc.get(k) or "")
            for k in (
                "name",
                "summary",
                "description",
                "appearance",
                "portrait_prompt",
                "voice_hint",
                "role",
            )
        )
        if _FEMALE_HINT_RE.search(probe):
            return True
        if _MALE_HINT_RE.search(probe):
            return False
        return False
    return bool(_FEMALE_HINT_RE.search(text)) or text in {"female", "f"}
