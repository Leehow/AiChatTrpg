"""advance_module_state helper used by ``backend/routes/session_time.py``.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_session_advance_time.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from routes.session_time import advance_module_state  # noqa: E402


def assert_eq(name: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{name} failed: expected {expected!r}, got {actual!r}")
    print(f"OK: {name}")


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def case_advance_simple_delta_updates_clock_and_period() -> None:
    state = {"day_count": 1, "in_game_time": "10:30", "in_game_period": "morning"}
    result = advance_module_state(state, 45)
    assert_eq("clock advanced", result["in_game_time"], "11:15")
    assert_eq("period stays morning", result["in_game_period"], "morning")
    assert_eq("day unchanged", result["day_count"], 1)
    assert_eq("elapsed accumulated", result["elapsed_minutes"], 45)


def case_advance_crosses_period_boundary() -> None:
    state = {"day_count": 2, "in_game_time": "11:30"}
    result = advance_module_state(state, 60)
    assert_eq("clock advanced into afternoon", result["in_game_time"], "12:30")
    assert_eq("period flipped to afternoon", result["in_game_period"], "afternoon")


def case_advance_rolls_over_day() -> None:
    state = {"day_count": 1, "in_game_time": "23:30", "elapsed_minutes": 90}
    result = advance_module_state(state, 60)
    assert_eq("clock wrapped past midnight", result["in_game_time"], "00:30")
    assert_eq("day rolled to 2", result["day_count"], 2)
    assert_eq("period is night", result["in_game_period"], "night")
    assert_eq("elapsed accumulated absolute delta", result["elapsed_minutes"], 150)


def case_advance_uses_default_09_when_uninitialized() -> None:
    state: dict = {}
    result = advance_module_state(state, 30)
    assert_eq("day defaults to 1", result["day_count"], 1)
    assert_eq("clock starts at 09:00 + 30m", result["in_game_time"], "09:30")
    assert_eq("morning period", result["in_game_period"], "morning")
    assert_eq("elapsed starts at delta", result["elapsed_minutes"], 30)


def case_advance_negative_delta_rewinds_clock() -> None:
    state = {"day_count": 3, "in_game_time": "00:30"}
    result = advance_module_state(state, -60)
    assert_eq("rewound clock", result["in_game_time"], "23:30")
    assert_eq("day rolled back", result["day_count"], 2)
    assert_eq("absolute delta added to elapsed", result["elapsed_minutes"], 60)


def case_advance_multiple_day_jump() -> None:
    state = {"day_count": 1, "in_game_time": "09:00"}
    # +27h = +1 day +3 hours
    result = advance_module_state(state, 27 * 60)
    assert_eq("clock advanced to 12:00", result["in_game_time"], "12:00")
    assert_eq("day advanced by 1", result["day_count"], 2)
    assert_eq("period afternoon", result["in_game_period"], "afternoon")


def case_advance_evening_and_night_buckets() -> None:
    evening = advance_module_state({"day_count": 1, "in_game_time": "17:00"}, 60)
    assert_eq("18:00 is evening", evening["in_game_period"], "evening")
    night = advance_module_state({"day_count": 1, "in_game_time": "21:00"}, 60)
    assert_eq("22:00 is night", night["in_game_period"], "night")


def main() -> None:
    case_advance_simple_delta_updates_clock_and_period()
    case_advance_crosses_period_boundary()
    case_advance_rolls_over_day()
    case_advance_uses_default_09_when_uninitialized()
    case_advance_negative_delta_rewinds_clock()
    case_advance_multiple_day_jump()
    case_advance_evening_and_night_buckets()
    print("All advance-time cases passed.")


if __name__ == "__main__":
    main()
