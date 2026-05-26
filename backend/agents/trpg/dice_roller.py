"""Seeded dice roller with replayable trace metadata."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any


_TERM_RE = re.compile(r"([+-]?)([^+-]+)")
_DICE_TERM_RE = re.compile(
    r"^(?P<count>\d*)d(?P<sides>\d+)(?:k(?P<keep>[hl])(?P<keep_count>\d+))?$",
    re.I,
)


@dataclass
class DiceRollResult:
    expression: str
    total: int
    rolls: list[dict[str, Any]]
    seed: str = ""
    notes: list[str] = field(default_factory=list)
    modifier: int = 0
    method: str = "standard"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        payload = {
            "expression": self.expression,
            "total": self.total,
            "rolls": self.rolls,
            "seed": self.seed,
            "notes": self.notes,
        }
        if self.modifier:
            payload["modifier"] = self.modifier
        if self.method != "standard":
            payload["method"] = self.method
        payload.update(self.extra)
        return payload

    def resolver_value(self) -> int | str:
        """Return the legacy CheckArgs.roll shape for existing resolvers."""

        kept_values = [
            int(roll["value"])
            for roll in self.rolls
            if roll.get("kept", True) and roll.get("kind", "die") == "die"
        ]
        if (
            self.method == "standard"
            and not self.modifier
            and len(kept_values) > 1
            and len(kept_values) == len(self.rolls)
        ):
            return ",".join(str(v) for v in kept_values)
        return self.total


class DiceRoller:
    """Small expression roller for runtime checks.

    Supported forms intentionally cover the current runtime surface first:
    ``1d20``, ``d100``, ``2d6+3``, ``2d20kh1``, ``2d20kl1``, and dice pools
    such as ``6d4``.
    """

    def __init__(self, *, seed: str = "") -> None:
        self.seed = str(seed or "").strip()
        self._rng = random.Random(self.seed) if self.seed else random.Random()

    def roll(self, expression: str) -> DiceRollResult:
        expr = _normalize_expression(expression)
        if not expr:
            raise ValueError("empty dice expression")
        rolls: list[dict[str, Any]] = []
        notes: list[str] = []
        total = 0
        modifier = 0
        for sign_text, raw_term in _TERM_RE.findall(expr):
            sign = -1 if sign_text == "-" else 1
            term = raw_term.strip()
            if not term:
                continue
            dice = _DICE_TERM_RE.match(term)
            if dice:
                term_total, term_rolls, term_notes = self._roll_dice_term(
                    dice,
                    sign=sign,
                    expression=term,
                )
                total += term_total
                rolls.extend(term_rolls)
                notes.extend(term_notes)
                continue
            if re.fullmatch(r"\d+", term):
                value = int(term) * sign
                total += value
                modifier += value
                continue
            raise ValueError(f"unsupported dice term: {term}")
        return DiceRollResult(
            expression=expr,
            total=total,
            rolls=rolls,
            seed=self.seed,
            notes=notes,
            modifier=modifier,
        )

    def roll_coc_d100(self, *, bonus: int = 0, penalty: int = 0) -> DiceRollResult:
        """Roll CoC-style d100 with bonus/penalty tens dice trace."""

        net = int(bonus or 0) - int(penalty or 0)
        extra_dice = min(abs(net), 5)
        if abs(net) > extra_dice:
            clipped = "bonus" if net > 0 else "penalty"
            notes = [f"{clipped} dice clipped from {abs(net)} to {extra_dice}"]
        else:
            notes = []
        tens_values = [self._rng.randint(0, 9) for _ in range(1 + extra_dice)]
        ones = self._rng.randint(0, 9)
        if net > 0:
            chosen_tens = min(tens_values)
            drop_reason = "drop_high"
            notes.append(f"bonus dice: choose lowest tens {chosen_tens}")
        elif net < 0:
            chosen_tens = max(tens_values)
            drop_reason = "drop_low"
            notes.append(f"penalty dice: choose highest tens {chosen_tens}")
        else:
            chosen_tens = tens_values[0]
            drop_reason = ""
        chosen_index = _first_index(tens_values, chosen_tens)
        total = chosen_tens * 10 + ones
        if total == 0:
            total = 100
        rolls: list[dict[str, Any]] = []
        for idx, value in enumerate(tens_values):
            kept = idx == chosen_index
            entry: dict[str, Any] = {
                "kind": "die",
                "role": "tens",
                "sides": 10,
                "value": value,
                "kept": kept,
            }
            if not kept and drop_reason:
                entry["reason"] = drop_reason
            rolls.append(entry)
        rolls.append({
            "kind": "die",
            "role": "ones",
            "sides": 10,
            "value": ones,
            "kept": True,
        })
        return DiceRollResult(
            expression="d100",
            total=total,
            rolls=rolls,
            seed=self.seed,
            notes=notes,
            method="coc_bonus_penalty",
            extra={
                "bonus": int(bonus or 0),
                "penalty": int(penalty or 0),
                "chosen_tens": chosen_tens,
                "ones": ones,
            },
        )

    def _roll_dice_term(
        self,
        match: re.Match[str],
        *,
        sign: int,
        expression: str,
    ) -> tuple[int, list[dict[str, Any]], list[str]]:
        raw_count = match.group("count")
        count = int(raw_count) if raw_count else 1
        sides = int(match.group("sides"))
        notes: list[str] = []
        if count < 1:
            notes.append(f"{expression}: count raised to 1")
            count = 1
        if count > 40:
            notes.append(f"{expression}: count clipped to 40")
            count = 40
        if sides < 2:
            notes.append(f"{expression}: sides raised to 2")
            sides = 2
        if sides > 1000:
            notes.append(f"{expression}: sides clipped to 1000")
            sides = 1000
        values = [self._rng.randint(1, sides) for _ in range(count)]
        keep_mode = (match.group("keep") or "").lower()
        keep_count = int(match.group("keep_count") or count)
        kept_indexes = set(range(count))
        drop_reason = ""
        if keep_mode:
            keep_count = max(1, min(keep_count, count))
            reverse = keep_mode == "h"
            ordered = sorted(
                range(count),
                key=lambda idx: values[idx],
                reverse=reverse,
            )
            kept_indexes = set(ordered[:keep_count])
            drop_reason = "drop_low" if keep_mode == "h" else "drop_high"
        rolls: list[dict[str, Any]] = []
        for idx, value in enumerate(values):
            kept = idx in kept_indexes
            entry: dict[str, Any] = {
                "kind": "die",
                "sides": sides,
                "value": value,
                "kept": kept,
            }
            if not kept and drop_reason:
                entry["reason"] = drop_reason
            if sign < 0:
                entry["sign"] = -1
            rolls.append(entry)
        term_total = sum(values[idx] for idx in kept_indexes) * sign
        return term_total, rolls, notes


def _normalize_expression(expression: str) -> str:
    return re.sub(r"\s+", "", str(expression or "")).lower()


def _first_index(values: list[int], target: int) -> int:
    for idx, value in enumerate(values):
        if value == target:
            return idx
    return 0
