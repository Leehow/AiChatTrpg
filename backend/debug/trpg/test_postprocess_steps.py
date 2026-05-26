"""Unit tests for ``services.trpg_postprocess_steps`` event helpers.

These exercise the in-memory event-shape logic. The DB-write path is
covered by integration; here we mock out the persistence so the tests
stay hermetic.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import services.trpg_postprocess_steps as ppmod
from services.trpg_postprocess_steps import (
    PHASE_COMPLETE_NAME,
    _make_event,
    record_step_standalone,
    step_timer,
    step_timer_with_db,
)


class MakeEventTests(unittest.TestCase):
    def test_basic_shape(self):
        ev = _make_event("foo", status="done", duration_ms=42, detail="ok")
        self.assertEqual(ev["type"], "postprocess_step")
        self.assertEqual(ev["name"], "foo")
        self.assertEqual(ev["status"], "done")
        self.assertEqual(ev["duration_ms"], 42)
        self.assertEqual(ev["detail"], "ok")
        self.assertTrue(ev["ts"])

    def test_detail_truncated_at_240(self):
        long = "x" * 1000
        ev = _make_event("foo", status="done", duration_ms=0, detail=long)
        self.assertEqual(len(ev["detail"]), 240)


class StandaloneRecordTests(unittest.IsolatedAsyncioTestCase):
    """Patch the row-lock writer with an in-memory list so we can verify
    the public record helpers without spinning up a DB."""

    async def asyncSetUp(self):
        self.captured: list[dict] = []

        async def fake_append(_db, _msg_id, event):
            self.captured.append(event)

        async def fake_record(db, message_id, name, *, status="done",
                              duration_ms=0, detail=""):
            await fake_append(
                db, message_id,
                _make_event(name, status=status, duration_ms=duration_ms, detail=detail),
            )

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_factory_ctx():
            yield None  # we only care that record() gets called

        class _FakeFactory:
            def __call__(self):
                return fake_factory_ctx()

        self._orig_record = ppmod.record_step
        self._orig_factory = ppmod.get_session_factory
        ppmod.record_step = fake_record  # type: ignore[assignment]
        ppmod.get_session_factory = lambda: _FakeFactory()  # type: ignore[assignment]

    async def asyncTearDown(self):
        ppmod.record_step = self._orig_record  # type: ignore[assignment]
        ppmod.get_session_factory = self._orig_factory  # type: ignore[assignment]

    async def test_record_step_standalone_emits_event(self):
        await record_step_standalone(
            "msg-1", "warm", duration_ms=100, detail="ok",
        )
        self.assertEqual(len(self.captured), 1)
        self.assertEqual(self.captured[0]["name"], "warm")
        self.assertEqual(self.captured[0]["duration_ms"], 100)

    async def test_record_step_standalone_skips_empty_message_id(self):
        await record_step_standalone("", "warm")
        self.assertEqual(self.captured, [])

    async def test_step_timer_emits_running_then_done(self):
        async with step_timer("msg-2", "loop") as handle:
            handle["detail"] = "5 items"
            await asyncio.sleep(0)
        self.assertEqual(len(self.captured), 2)
        self.assertEqual(self.captured[0]["status"], "running")
        self.assertEqual(self.captured[1]["status"], "done")
        # Detail set in the handle should propagate to the done event.
        self.assertEqual(self.captured[1]["detail"], "5 items")
        self.assertGreaterEqual(self.captured[1]["duration_ms"], 0)


class StepTimerWithDbTests(unittest.IsolatedAsyncioTestCase):
    """Same idea but for the inline (caller-supplied db) path."""

    async def asyncSetUp(self):
        self.captured: list[dict] = []

        async def fake_record(db, message_id, name, *, status="done",
                              duration_ms=0, detail=""):
            self.captured.append(
                _make_event(name, status=status, duration_ms=duration_ms, detail=detail)
            )

        self._orig_record = ppmod.record_step
        ppmod.record_step = fake_record  # type: ignore[assignment]

    async def asyncTearDown(self):
        ppmod.record_step = self._orig_record  # type: ignore[assignment]

    async def test_pairs_running_and_done(self):
        async with step_timer_with_db(None, "msg-3", "warm"):
            pass
        self.assertEqual([e["status"] for e in self.captured], ["running", "done"])

    async def test_skipped_on_empty_message_id(self):
        async with step_timer_with_db(None, "", "warm"):
            pass
        self.assertEqual(self.captured, [])


class PhaseCompleteConstantTest(unittest.TestCase):
    def test_constant_matches_frontend_expected(self):
        # The frontend keys off this exact string when deciding to stop
        # polling. Any rename here is a breaking change.
        self.assertEqual(PHASE_COMPLETE_NAME, "phase3_complete")


if __name__ == "__main__":
    unittest.main()
