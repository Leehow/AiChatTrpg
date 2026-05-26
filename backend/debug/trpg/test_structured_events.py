"""Smoke tests for IC structured event markers."""

from __future__ import annotations

import unittest

from services.trpg_structured_events import (
    StructuredEventsStreamFilter,
    parse_structured_events,
    strip_structured_events,
)


class StructuredEventTests(unittest.TestCase):
    def test_parse_and_strip_structured_events(self):
        text = (
            "店主压低声音。\n"
            "[STRUCTURED_EVENTS]{\"events\":[{\"type\":\"NPC_REACTED\","
            "\"actor_id\":\"keeper\",\"target_ids\":[\"pc\"],"
            "\"content\":\"店主拒绝在大厅里谈失踪学生。\"}]}"
            "[/STRUCTURED_EVENTS]"
        )

        parsed = parse_structured_events(text, scene_id="tavern", turn_id=4)

        self.assertEqual(len(parsed.events), 1)
        self.assertEqual(parsed.events[0].actor_id, "keeper")
        self.assertEqual(parsed.events[0].target_ids, ["pc"])
        self.assertEqual(parsed.events[0].scene_id, "tavern")
        self.assertNotIn("STRUCTURED_EVENTS", strip_structured_events(text))

    def test_stream_filter_suppresses_marker_body(self):
        filt = StructuredEventsStreamFilter()
        chunks = [
            "可见叙事。",
            "[STRUCTURED",
            "_EVENTS]{\"events\":[{\"content\":\"hidden\"}]}",
            "[/STRUCTURED_EVENTS]",
            "",
        ]
        visible = "".join(filt.feed(chunk) for chunk in chunks) + filt.flush()

        self.assertEqual(visible, "可见叙事。")
        self.assertNotIn("hidden", visible)


if __name__ == "__main__":
    unittest.main()
