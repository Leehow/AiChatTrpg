"""Runtime CHECK log persistence helpers.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_check_logs.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.trpg.check_resolver import CheckArgs  # noqa: E402
from agents.trpg.check_runtime import execute_check_runtime  # noqa: E402
import services.trpg_check_logs as check_logs  # noqa: E402


check_logs.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def case_record_check_execution_appends_log_and_history() -> None:
    db = FakeDb()
    session = SimpleNamespace(id="sess-check-log", dice_history=[])
    execution = execute_check_runtime(
        CheckArgs(
            skill="开锁",
            value=3,
            roll=12,
            extras={"actor": "pc", "roll_seed": "check-log-seed"},
        ),
        {"engine": "d20_vs_dc", "default_dc": 10},
        auto_roll=False,
        source="debug_check_log",
    )
    log = check_logs.record_check_execution(
        db,
        session,  # type: ignore[arg-type]
        execution,
        message_id="msg-1",
        source="inline_check",
    )
    assert_true("log added to db", log in db.added)
    assert_eq("log session", log.session_id, "sess-check-log")
    assert_eq("log message", log.message_id, "msg-1")
    assert_eq("log actor", log.actor_id, "pc")
    assert_eq("log engine", log.engine, "d20_vs_dc")
    assert_eq("log seed", log.seed, "check-log-seed")
    assert_eq("log request skill", log.request_json["skill"], "开锁")
    assert_true("log result passed", log.result_json["passed"] is True)
    assert_eq("history count", len(session.dice_history), 1)
    hist = session.dice_history[0]
    assert_eq("history log id", hist["check_log_id"], log.id)
    assert_eq("history message", hist["message_id"], "msg-1")
    assert_eq("history seed", hist["seed"], "check-log-seed")
    assert_true("history trace", isinstance(hist["trace"], dict), repr(hist))


def main() -> None:
    case_record_check_execution_appends_log_and_history()
    print("All check log cases passed.")


if __name__ == "__main__":
    main()
