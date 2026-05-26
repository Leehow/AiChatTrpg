"""Mode selection — which BP builder + which phase logic this turn runs.

Three modes cover everything: GUIDE (character setup), IC (in-character play),
BREAK (between adventures). Selection is a pure function of session state +
optional caller hint. The framework does NOT support an in-game "rewrite the
character" path — once `game_started` flips True it stays True."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from .models import SessionState


class Mode(str, Enum):
    GUIDE = "guide"
    IC = "ic"
    BREAK = "break"


ModeHint = Literal["auto", "guide", "ic", "break"]


def select_mode(state: SessionState, hint: ModeHint = "auto") -> Mode:
    if hint != "auto":
        return Mode(hint)
    if not state.game_started:
        return Mode.GUIDE
    if state.in_break:
        return Mode.BREAK
    return Mode.IC
