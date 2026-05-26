"""Deterministic check resolution for TRPG dice checks.

The GM model emits a ``[CHECK ...]`` marker declaring a check, and this
module resolves it purely in Python — taking threshold arithmetic out of
the LLM's hands so 20 is never compared as "but not ≤37" again.

Resolution engines live in ``check_engines.py``. This module owns:
  - Public dataclasses (``CheckArgs``, ``CheckResult``)
  - Engine dispatch
  - Label resolution (spec overrides → engine defaults)
  - Shared argument coercion helpers
  - Final ``[dice]`` block rendering

The rendered ``[dice]`` block drops straight into the existing frontend
collapse/expand UI — no client change needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .check_engine_registry import get_default_labels, get_engine

logger = logging.getLogger("chatlab.trpg")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CheckArgs:
    """Parsed ``[CHECK ...]`` marker arguments."""
    skill: str = ""
    value: Optional[float] = None
    roll: Any = None  # int, list[int], or raw string for engine to parse
    difficulty: str = "regular"
    bonus: int = 0
    penalty: int = 0
    pool: str = ""   # e.g. "6d4" for pool_count_n
    target: Optional[int] = None  # per-die pass threshold in pool engines
    reason: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Uniform resolution result."""
    tier: str = "failure"
    tier_label: str = ""           # localized label from spec
    passed: bool = False
    explanation: str = ""          # human-readable arithmetic justification
    thresholds: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    engine: str = ""
    roll_display: str = ""
    side_effects: Dict[str, Any] = field(default_factory=dict)
    result_axes: Dict[str, Any] = field(default_factory=dict)


def label(spec: Optional[Dict[str, Any]], engine: str, key: str) -> str:
    """Spec override → engine default → raw key fallback."""
    labels = (spec or {}).get("labels") or {}
    default = get_default_labels(engine)
    return labels.get(key) or default.get(key, key)


# ---------------------------------------------------------------------------
# Shared argument coercion
# ---------------------------------------------------------------------------


def coerce_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def coerce_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_roll_list(raw: Any) -> List[int]:
    """Accept int, list, or comma/semicolon-separated string → list[int]."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [coerce_int(x) for x in raw]
    if isinstance(raw, (int, float)):
        return [int(raw)]
    s = str(raw).strip().strip("[]")
    if not s:
        return []
    out: List[int] = []
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(coerce_int(part))
    return out


def resolve_check(
    args: CheckArgs, spec: Optional[Dict[str, Any]],
) -> CheckResult:
    """Dispatch to the engine named by ``spec['engine']``.

    Unknown / missing engine falls back to ``custom_llm`` (graceful).
    """
    engine_key = ((spec or {}).get("engine") or "custom_llm").lower()
    fn = get_engine(engine_key)
    try:
        return fn(args, spec or {})
    except Exception as e:
        logger.warning(
            "[TRPG] check_resolver engine=%s raised: %s",
            engine_key, e, exc_info=True,
        )
        return CheckResult(
            tier="unresolved",
            tier_label=label(spec, engine_key, "unresolved") or "仅显示骰值",
            passed=False,
            explanation="规则判定暂时无法自动解析；仅显示骰值，并以叙事结果为准。",
            warnings=[f"engine {engine_key} raised {type(e).__name__}"],
            engine=engine_key,
            roll_display=str(args.roll or "?"),
        )


# ---------------------------------------------------------------------------
# Renderer — CheckResult → [dice]...[/dice] block text
# ---------------------------------------------------------------------------


_TIER_EMOJI = {
    "critical": "🌟", "extreme": "✨", "hard": "💪", "regular": "✅",
    "success": "✅", "hit": "✅", "partial": "⚠️", "special": "✨",
    "crit": "🌟", "triscendence": "🌟", "failure": "❌", "miss": "❌",
    "fumble": "💀", "manual_resolution_required": "🎲", "unresolved": "🎲",
}


# Skill / attribute names the GM may emit in English.
# Values are the canonical Chinese display terms. Normalization collapses
# underscores/whitespace and lowercases — so "Spot Hidden", "spot_hidden",
# and "SPOT HIDDEN" all hit the same entry.
_SKILL_LABELS: Dict[str, str] = {
    # Resources / attributes
    "str": "力量", "dex": "敏捷", "int": "智力", "con": "体质",
    "pow": "意志", "siz": "体型", "app": "外貌", "edu": "教育",
    "san": "理智", "sanity": "理智", "luck": "幸运", "hp": "生命值",
    "mp": "魔法值", "hit points": "生命值", "magic points": "魔法值",
    # Combat
    "dodge": "闪避", "brawl": "近战", "fighting": "近战", "fighting brawl": "近战",
    "firearms": "射击", "firearms handgun": "射击(手枪)", "firearms rifle": "射击(步枪)",
    "throw": "投掷",
    # Perception / investigation
    "listen": "聆听", "spot hidden": "侦查", "psychology": "心理学",
    "track": "追踪", "navigate": "导航", "library use": "图书馆使用",
    "appraise": "估价",
    # Social
    "fast talk": "话术", "persuade": "说服", "intimidate": "恐吓",
    "charm": "取悦", "disguise": "伪装",
    # Physical
    "climb": "攀爬", "jump": "跳跃", "swim": "游泳", "stealth": "潜行",
    "sleight of hand": "手法",
    # Practical
    "drive auto": "汽车驾驶", "mechanical repair": "机械维修",
    "electrical repair": "电器维修", "first aid": "急救", "medicine": "医学",
    "locksmith": "锁匠", "pilot": "驾驶", "ride": "骑术", "operate heavy machinery": "操作重型机械",
    # Knowledge
    "occult": "神秘学", "cthulhu mythos": "克苏鲁神话",
    "archaeology": "考古学", "history": "历史", "science": "科学",
    "anthropology": "人类学", "natural world": "博物学",
    "accounting": "会计", "law": "法律", "art craft": "艺术与手艺",
    "credit rating": "信用评级", "language own": "母语", "language other": "外语",
}

_DIFFICULTY_LABELS: Dict[str, str] = {
    "regular": "常规", "hard": "困难", "extreme": "极难",
}

_SIDE_EFFECT_LABELS: Dict[str, str] = {
    "san_loss": "SAN 损失",
    "sanity_loss": "SAN 损失",
    "sanity_delta": "SAN 变化",
    "san_delta": "SAN 变化",
    "sanity_spent": "SAN 消耗",
    "hp_delta": "生命值变化",
    "magic_points_spent": "魔法值消耗",
}


def _normalize_key(text: str) -> str:
    """Lowercase + collapse ``_``/whitespace, so ``Spot_Hidden`` ≡ ``spot hidden``."""
    return re.sub(r"[_\s]+", " ", str(text or "").strip().lower())


def _translate_skill(raw: str) -> str:
    """English skill name → Chinese if known; otherwise return as-is."""
    if not raw:
        return raw
    return _SKILL_LABELS.get(_normalize_key(raw), raw)


def _translate_difficulty(raw: str) -> str:
    """English difficulty → Chinese; otherwise return as-is."""
    if not raw:
        return raw
    return _DIFFICULTY_LABELS.get(_normalize_key(raw), raw)


def _threshold_line(args: CheckArgs, result: CheckResult) -> str:
    """Render the per-engine "threshold summary" line for the [dice] block."""
    th = result.thresholds or {}
    bits: List[str] = []
    if result.engine == "coc_7e_d100":
        bits.append(f"常规≤{th.get('regular', '?')}")
        bits.append(f"困难≤{th.get('hard', '?')}")
        bits.append(f"极难≤{th.get('extreme', '?')}")
    elif result.engine == "brp_d100":
        bits.append(f"常规≤{th.get('regular', '?')}")
        bits.append(f"特殊≤{th.get('special', '?')}")
    elif result.engine == "d20_vs_dc":
        bits.append(f"DC {th.get('dc', '?')}")
    elif result.engine == "pbta_2d6":
        bits.append(f"完全≥{th.get('hit', '?')}")
        bits.append(f"部分≥{th.get('partial', '?')}")
    elif result.engine == "pool_count_n":
        bits.append(f"每骰≥{th.get('per_die', '?')}")
        bits.append(f"需要{th.get('required', '?')} 个")
    if not bits:
        return ""
    value_str = str(int(args.value)) if args.value is not None else ""
    skill_display = _translate_skill(args.skill)
    return f"技能/数值: {skill_display} {value_str} | " + ", ".join(bits)


def render_dice_block(args: CheckArgs, result: CheckResult) -> str:
    """Render a uniform ``[dice]...[/dice]`` block from the resolution."""
    emoji = _TIER_EMOJI.get(result.tier, "🎲")
    skill_display = _translate_skill(args.skill) or "检定"
    heading = f"{skill_display} — {emoji} {result.tier_label}"

    lines = [heading]
    th_line = _threshold_line(args, result)
    if th_line:
        lines.append(th_line)
    if args.reason:
        lines.append(f"情境: {args.reason}")
    if args.difficulty and args.difficulty != "regular":
        lines.append(f"要求难度: {_translate_difficulty(args.difficulty)}")
    lines.append(f"骰值: {result.roll_display}")
    lines.append(f"判定: {result.explanation}")
    if result.side_effects:
        lines.extend(_side_effect_lines(result.side_effects))

    return "[dice]\n" + "\n".join(lines) + "\n[/dice]"


def _side_effect_lines(side_effects: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    generic: List[str] = []
    for key, value in side_effects.items():
        label_text = _SIDE_EFFECT_LABELS.get(str(key), "")
        if label_text:
            lines.append(f"{label_text}: {value}")
        else:
            generic.append(f"{key}: {value}")
    if generic:
        lines.append("副作用: " + ", ".join(generic))
    return lines
