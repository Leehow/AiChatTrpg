"""LivenessCard inference.

This is intentionally deterministic and cheap. Richer LLM-based enrichment can
run after the visible reply, but the foreground path should always have a small
card to work with.
"""

from __future__ import annotations

from typing import Any

from .common import clamp, get_value, short_text, text_blob
from .models import LivenessCard


def liveness_card_from_npc(npc: Any, profile: Any | None = None) -> LivenessCard:
    npc_id = str(
        get_value(npc, "key")
        or get_value(npc, "npc_id")
        or get_value(profile, "npc_id")
        or "unknown_npc"
    )
    existing = get_value(npc, "liveness_card_v2") or get_value(npc, "liveness_card")
    if isinstance(existing, dict):
        return _from_dict(npc_id, existing)

    role = str(get_value(npc, "role") or get_value(profile, "narrative_role") or "").lower()
    blob = text_blob(npc, get_value(profile, "public_card"), get_value(profile, "private_card"))
    card = LivenessCard(npc_id=npc_id)

    if any(word in blob for word in ["店主", "shopkeeper", "老板", "酒馆"]):
        card.default_stance = "busy_but_watchful"
        card.physical_tells = ["把同一个杯子擦得过久", "听到敏感话题时看向后门"]
        card.speech_habits = ["先否认，再补一句模糊提醒", "公开场合用短句回答"]
        card.avoidance_habits = ["假装忙着招呼其他客人", "把谈话转到私下"]
        card.daily_routine_hint = "打烊前会检查后门、柜台和账本。"
    elif any(word in blob for word in ["警探", "警察", "detective", "police"]):
        card.default_stance = "measured_professional"
        card.physical_tells = ["说话前会扫视出口和旁听者", "习惯把问题拆成时间线"]
        card.speech_habits = ["用事实纠正夸张推测", "会反问玩家证据来源"]
        card.avoidance_habits = ["避免在没有证据时下结论"]
        card.daily_routine_hint = "会在白天追查线索，夜里整理记录。"
    elif any(word in blob for word in ["邪教", "祭司", "反派", "cult", "priest", "antagonist", "villain"]):
        card.default_stance = "controlled_mask"
        card.social_energy = 0.65
        card.proactivity = 0.55
        card.interrupt_threshold = 0.55
        card.physical_tells = ["愤怒时反而放慢语速", "被逼问时先观察谁在旁听"]
        card.speech_habits = ["用反问和道德指责转移话题", "把威胁包装成劝告"]
        card.avoidance_habits = ["不直接承认组织或仪式", "把矛头引向替罪羊"]
        card.private_line_they_wont_cross = "不会无触发地坦白核心秘密。"
    elif any(word in blob for word in ["目击", "证人", "witness", "害怕", "wary"]):
        card.default_stance = "nervous_witness"
        card.social_energy = 0.35
        card.proactivity = 0.25
        card.interrupt_threshold = 0.85
        card.physical_tells = ["回答前会确认附近有没有人在听", "紧张时手指攥紧衣角"]
        card.speech_habits = ["句子短，容易改口", "先问玩家能不能保护自己"]
        card.avoidance_habits = ["避免说出具体姓名", "一旦公开被逼问就想离开"]
    else:
        card.default_stance = "surface_neutral"
        card.physical_tells = ["视线会短暂追随玩家的动作"]
        card.speech_habits = ["回答简短，不主动展开无关信息"]
        card.avoidance_habits = ["不确定时会看向更有权威的人"]

    summary = short_text(get_value(npc, "summary") or get_value(profile, "narrative_role"), max_len=180)
    if summary:
        card.personal_stakes.append(f"与当前身份相关：{summary}")
    return card


def _from_dict(npc_id: str, raw: dict[str, Any]) -> LivenessCard:
    card = LivenessCard(npc_id=str(raw.get("npc_id") or npc_id))
    for key in [
        "default_stance", "daily_routine_hint", "private_line_they_wont_cross",
    ]:
        if raw.get(key):
            setattr(card, key, str(raw[key]))
    for key in ["social_energy", "proactivity", "interrupt_threshold"]:
        if key in raw:
            setattr(card, key, clamp(raw[key]))
    for key in [
        "physical_tells", "speech_habits", "avoidance_habits", "comfort_actions", "personal_stakes",
    ]:
        value = raw.get(key)
        if isinstance(value, list):
            setattr(card, key, [short_text(v, max_len=160) for v in value if str(v).strip()][:5])
    return card
