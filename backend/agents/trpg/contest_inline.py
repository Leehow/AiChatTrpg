"""Streaming ``[CONTEST ...]`` marker replacement for TRPG GM output.

The first live use-case is CoC 7e melee opposed resolution:

- attacker vs Dodge
- attacker vs Fight Back
- critical/extreme success comparison
- deterministic winner selection
- deterministic "extreme damage / impale" mode selection

Optional damage-roll fields let the backend compute real damage totals too,
but even when they are absent the backend still decides the opposed outcome
and renders the correct rules branch for the player.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Iterator, List, Optional, Tuple

from .check_resolver import CheckArgs, parse_roll_list
from .contest_engine import (
    ContestSide,
    ContestResolution,
    coc_melee_contest_policy,
    resolve_contest,
)
from .coc_runtime import coerce_coc_d100_check_spec, coc_tier_rule_effect

logger = logging.getLogger("chatlab.trpg")

MARKER_OPEN = "[CONTEST"
MAX_MARKER_CHARS = 1600
_POTENTIAL_MARKER_PREFIXES = frozenset({
    "[", "[C", "[CO", "[CON", "[CONT", "[CONTE", "[CONTES", "[CONTEST",
})

_ATTR_RE = re.compile(
    r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
    r'(?:"(?P<qval>[^"]*)"|'
    r"'(?P<sval>[^']*)'|"
    r'(?P<bval>[^\s\]"]+))'
)


@dataclass
class ContestMarker:
    system: str
    mode: str
    reaction: str
    reason: str
    attacker: ContestSide
    defender: ContestSide
    attrs: Dict[str, Any]


def _find_unquoted_close(text: str, start: int) -> int:
    quote: Optional[str] = None
    depth = 0
    j = start
    while j < len(text):
        ch = text[j]
        if quote:
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            if depth == 0:
                return j
            depth -= 1
        j += 1
    return -1


def _coerce_extra(raw: str) -> Any:
    text = str(raw or "").strip()
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _normalize_reaction(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _needs_auto_roll(raw: Any) -> bool:
    if raw is None:
        return True
    text = str(raw).strip().lower()
    return text in {"", "auto", "random", "roll"}


def parse_contest_marker(
    payload: str,
    spec: Optional[Dict[str, Any]],
) -> ContestMarker:
    attrs: Dict[str, Any] = {}
    for match in _ATTR_RE.finditer(payload or ""):
        key = match.group("key").lower()
        raw = match.group("qval") or match.group("sval") or match.group("bval") or ""
        attrs[key] = _coerce_extra(raw)

    system = str(attrs.get("system") or ((spec or {}).get("engine") or "")).strip().lower()
    mode = str(attrs.get("mode") or attrs.get("kind") or "melee").strip().lower()
    reaction = _normalize_reaction(attrs.get("reaction"))
    reason = str(attrs.get("reason") or "").strip()

    attacker = ContestSide(
        role="attacker",
        label=str(attrs.get("attacker") or attrs.get("attacker_label") or "攻击方").strip(),
        args=CheckArgs(
            skill=str(attrs.get("attacker_skill") or "").strip(),
            value=_as_int(attrs.get("attacker_value")),
            roll=attrs.get("attacker_roll"),
            difficulty=str(attrs.get("attacker_difficulty") or "regular"),
            reason=reason,
        ),
        spec=spec or {},
        metadata={
            "damage": attrs.get("attacker_damage"),
            "damage_roll": attrs.get("attacker_damage_roll"),
            "damage_bonus": attrs.get("attacker_damage_bonus"),
            "damage_bonus_max": attrs.get("attacker_damage_bonus_max"),
            "impaling": attrs.get("attacker_impaling"),
            "hp": attrs.get("attacker_hp"),
        },
    )
    defender = ContestSide(
        role="defender",
        label=str(attrs.get("defender") or attrs.get("defender_label") or "防守方").strip(),
        args=CheckArgs(
            skill=str(attrs.get("defender_skill") or "").strip(),
            value=_as_int(attrs.get("defender_value")),
            roll=attrs.get("defender_roll"),
            difficulty=str(attrs.get("defender_difficulty") or "regular"),
            reason=reason,
        ),
        spec=spec or {},
        metadata={
            "damage": attrs.get("defender_damage"),
            "damage_roll": attrs.get("defender_damage_roll"),
            "damage_bonus": attrs.get("defender_damage_bonus"),
            "damage_bonus_max": attrs.get("defender_damage_bonus_max"),
            "impaling": attrs.get("defender_impaling"),
            "hp": attrs.get("defender_hp"),
        },
    )
    return ContestMarker(
        system=system,
        mode=mode,
        reaction=reaction,
        reason=reason,
        attacker=attacker,
        defender=defender,
        attrs=attrs,
    )


def _parse_damage_expr(expr: Any) -> Tuple[int, int]:
    """Return ``(max_total_without_db, constant_total)`` for the weapon expr."""
    text = str(expr or "").strip().upper()
    if not text:
        return 0, 0
    text = text.replace("DB", "")
    token_re = re.compile(r'([+-]?\s*\d+D\d+|[+-]?\s*\d+)')
    max_total = 0
    const_total = 0
    for token in token_re.findall(text):
        cleaned = token.replace(" ", "")
        sign = -1 if cleaned.startswith("-") else 1
        core = cleaned.lstrip("+-")
        if "D" in core:
            count_s, sides_s = core.split("D", 1)
            count = int(count_s or "1")
            sides = int(sides_s)
            max_total += sign * count * sides
        else:
            value = sign * int(core)
            max_total += value
            const_total += value
    return max_total, const_total


def _sum_rolls(raw: Any) -> Optional[int]:
    vals = parse_roll_list(raw)
    if not vals:
        return None
    return sum(vals)


def _tier_cn(tier: str) -> str:
    mapping = {
        "critical": "大成功",
        "extreme": "极难成功",
        "hard": "困难成功",
        "regular": "常规成功",
        "failure": "失败",
        "fumble": "大失败",
    }
    return mapping.get(str(tier or "").strip().lower(), str(tier or "").strip())


def _outcome_cn(outcome: str) -> str:
    return {
        "attacker_wins": "攻击方获胜",
        "defender_wins": "防守方获胜",
        "stalemate": "双方僵持",
    }.get(outcome, outcome)


def _reaction_cn(reaction: str) -> str:
    return {
        "dodge": "闪避",
        "fight_back": "反击",
        "fightback": "反击",
    }.get(reaction, reaction)


def _compute_damage(
    resolution: ContestResolution,
) -> Tuple[List[str], List[str]]:
    effects = list(resolution.planned_effects or [])
    if not effects:
        return [], []
    effect = effects[0]
    source_key = str(effect.get("source") or "").strip().lower()
    target_key = str(effect.get("target") or "").strip().lower()
    if source_key not in {"attacker", "defender"} or target_key not in {"attacker", "defender"}:
        return [], ["unsupported contest effect payload"]

    source_side = resolution.attacker if source_key == "attacker" else resolution.defender
    source_result = resolution.attacker_result if source_key == "attacker" else resolution.defender_result
    target_side = resolution.attacker if target_key == "attacker" else resolution.defender

    expr = source_side.metadata.get("damage")
    roll_sum = _sum_rolls(source_side.metadata.get("damage_roll"))
    bonus = _as_int(source_side.metadata.get("damage_bonus")) or 0
    bonus_max = _as_int(source_side.metadata.get("damage_bonus_max"))
    if bonus_max is None:
        bonus_max = bonus
    impaling = _as_bool(source_side.metadata.get("impaling"))
    max_weapon, const_total = _parse_damage_expr(expr)

    lines: List[str] = [
        f"命中方: {source_side.label}",
        f"伤害目标: {target_side.label}",
    ]
    warnings: List[str] = []

    total: Optional[int] = None
    damage_mode = "normal"

    source_is_active_attacker = source_key == "attacker" and resolution.outcome == "attacker_wins"
    if source_is_active_attacker and source_result.tier in {"critical", "extreme"}:
        if impaling:
            damage_mode = "extreme_impale"
            lines.append("伤害模式: 极限成功(穿刺) -> 最大武器伤害 + 最大DB + 再掷一次武器伤害")
            if roll_sum is not None:
                total = max_weapon + bonus_max + roll_sum
                lines.append(f"结算: {max_weapon} + {bonus_max} + {roll_sum} = {total}")
            else:
                warnings.append("impaling critical/extreme damage missing weapon damage roll")
        else:
            damage_mode = "extreme_max"
            total = max_weapon + bonus_max
            lines.append("伤害模式: 极限成功 -> 最大武器伤害 + 最大DB")
            lines.append(f"结算: {max_weapon} + {bonus_max} = {total}")
    else:
        lines.append("伤害模式: 普通伤害")
        if roll_sum is not None:
            total = roll_sum + const_total + bonus
            if const_total:
                lines.append(f"结算: {roll_sum} + {const_total} + {bonus} = {total}")
            else:
                lines.append(f"结算: {roll_sum} + {bonus} = {total}")
        else:
            warnings.append("normal damage missing damage roll")

    if expr:
        lines.append(f"伤害公式: {expr}")
    if total is not None:
        lines.append(f"实际伤害: {total}")
        source_hp = _as_int(source_side.metadata.get("hp"))
        target_hp = _as_int(target_side.metadata.get("hp"))
        if source_hp is not None:
            lines.append(f"{source_side.label} HP: {source_hp} -> {source_hp}")
        if target_hp is not None:
            lines.append(f"{target_side.label} HP: {target_hp} -> {max(target_hp - total, 0)}")
    else:
        if damage_mode == "extreme_impale":
            lines.append("实际伤害: 需再提供一次武器伤害骰值后才能结算")
        else:
            lines.append("实际伤害: 需提供伤害骰值后才能结算")

    return lines, warnings


def _special_tier_lines(resolution: ContestResolution) -> List[str]:
    lines: List[str] = []
    for side, result in (
        (resolution.attacker, resolution.attacker_result),
        (resolution.defender, resolution.defender_result),
    ):
        effect = coc_tier_rule_effect(result.tier, contest=True)
        if effect:
            lines.append(f"{side.label}额外效果: {effect}")
    return lines


def render_contest_block(marker: ContestMarker, resolution: ContestResolution) -> str:
    lines: List[str] = [
        f"对抗检定 — CoC 近战 / {_reaction_cn(marker.reaction)}",
    ]
    if marker.reason:
        lines.append(f"情境: {marker.reason}")
    lines.append(
        f"攻击方: {marker.attacker.label} | {marker.attacker.args.skill} {marker.attacker.args.value} | "
        f"骰值 {resolution.attacker_result.roll_display} | {_tier_cn(resolution.attacker_result.tier)}"
    )
    lines.append(
        f"防守方: {marker.defender.label} | {marker.defender.args.skill} {marker.defender.args.value} | "
        f"骰值 {resolution.defender_result.roll_display} | {_tier_cn(resolution.defender_result.tier)}"
    )
    lines.append(f"结果: {_outcome_cn(resolution.outcome)}")
    lines.append(f"判定: {resolution.explanation}")

    damage_lines, damage_warnings = _compute_damage(resolution)
    if damage_lines:
        lines.extend(damage_lines)
    lines.extend(_special_tier_lines(resolution))

    warnings = list(resolution.warnings or []) + damage_warnings
    if warnings:
        lines.append("注意: " + " | ".join(warnings))

    return "[dice]\n" + "\n".join(lines) + "\n[/dice]"


class ContestMarkerStream:
    def __init__(self, spec: Optional[Dict[str, Any]]):
        self.spec = spec or {}
        self._buffer = ""
        self._output = ""
        self._buffering = False
        self._pending_prefix = ""

    def feed(self, text: str) -> None:
        if not text and not self._pending_prefix:
            return
        if self._pending_prefix:
            text = self._pending_prefix + text
            self._pending_prefix = ""
        remaining = self._buffer + text if self._buffering else text
        self._buffer = ""

        i = 0
        while i < len(remaining):
            if self._buffering:
                close_idx = _find_unquoted_close(remaining, i)
                if close_idx == -1:
                    self._buffer = remaining[i:]
                    if len(self._buffer) > MAX_MARKER_CHARS:
                        logger.warning("[TRPG] [CONTEST] marker overflow (%d chars), flushing verbatim", len(self._buffer))
                        self._output += self._buffer
                        self._buffer = ""
                        self._buffering = False
                    break
                marker_body = remaining[i:close_idx]
                self._output += self._resolve(marker_body)
                i = close_idx + 1
                self._buffering = False
                continue

            open_idx = remaining.find(MARKER_OPEN, i)
            if open_idx == -1:
                self._output += remaining[i:]
                break

            peek_start = open_idx + len(MARKER_OPEN)
            if peek_start >= len(remaining):
                self._output += remaining[i:open_idx]
                self._pending_prefix = remaining[open_idx:]
                return
            after = remaining[peek_start:peek_start + 1]
            if after not in (" ", "]", "\t", "\n"):
                self._output += remaining[i:open_idx + 1]
                i = open_idx + 1
                continue

            self._output += remaining[i:open_idx]
            i = open_idx + len(MARKER_OPEN)
            self._buffering = True
            self._buffer = ""

        if not self._buffering and self._output:
            for length in range(min(len(MARKER_OPEN), len(self._output)), 0, -1):
                tail = self._output[-length:]
                if tail in _POTENTIAL_MARKER_PREFIXES:
                    self._pending_prefix = tail
                    self._output = self._output[:-length]
                    break

    def _resolve(self, marker_body: str) -> str:
        try:
            marker = parse_contest_marker(marker_body, self.spec)
        except Exception as exc:
            logger.warning("[TRPG] Failed to parse [CONTEST] marker: %s", exc, exc_info=True)
            return "[CONTEST" + marker_body + "]"

        spec = coerce_coc_d100_check_spec(self.spec, system=marker.system)
        marker.attacker.spec = spec
        marker.defender.spec = spec
        engine = str((spec or {}).get("engine") or "").strip().lower()
        if engine != "coc_7e_d100" or marker.mode != "melee":
            logger.info("[TRPG] Unsupported [CONTEST] marker passthrough engine=%s mode=%s", engine, marker.mode)
            return "[CONTEST" + marker_body + "]"

        if _needs_auto_roll(marker.attacker.args.roll):
            marker.attacker.args.roll = random.randint(1, 100)
        if _needs_auto_roll(marker.defender.args.roll):
            marker.defender.args.roll = random.randint(1, 100)

        try:
            resolution = resolve_contest(
                attacker=marker.attacker,
                defender=marker.defender,
                policy=coc_melee_contest_policy(marker.reaction),
            )
        except Exception as exc:
            logger.warning("[TRPG] Failed to resolve [CONTEST] marker: %s", exc, exc_info=True)
            return "[CONTEST" + marker_body + "]"

        return render_contest_block(marker, resolution)

    def drain(self) -> str:
        out, self._output = self._output, ""
        return out

    def flush(self) -> str:
        if self._pending_prefix:
            self._output += self._pending_prefix
            self._pending_prefix = ""
        if self._buffering and self._buffer:
            self._output += "[CONTEST" + self._buffer
            self._buffer = ""
            self._buffering = False
        return self.drain()


async def replace_contests_in_stream(
    source: AsyncGenerator[Dict[str, Any], None],
    spec: Optional[Dict[str, Any]],
) -> AsyncGenerator[Dict[str, Any], None]:
    buf = ContestMarkerStream(spec)
    async for event in source:
        if event.get("type") != "content":
            tail = buf.drain()
            if tail:
                yield {"type": "content", "content": tail}
            yield event
            continue
        buf.feed(event.get("content", ""))
        out = buf.drain()
        if out:
            yield {"type": "content", "content": out}
    tail = buf.flush()
    if tail:
        yield {"type": "content", "content": tail}


def replace_contests_in_text(text: str, spec: Optional[Dict[str, Any]]) -> str:
    buf = ContestMarkerStream(spec)
    buf.feed(text)
    return buf.flush() or buf.drain()


def iter_contest_markers(text: str) -> Iterator[Tuple[int, int, str]]:
    i = 0
    while True:
        idx = text.find(MARKER_OPEN, i)
        if idx == -1:
            return
        after = text[idx + len(MARKER_OPEN):idx + len(MARKER_OPEN) + 1]
        if after not in (" ", "]", "\t", "\n"):
            i = idx + 1
            continue
        close = text.find("]", idx + len(MARKER_OPEN))
        if close == -1:
            return
        yield idx, close + 1, text[idx + len(MARKER_OPEN):close]
        i = close + 1
