"""Tests for `[name_reveal]` marker parsing and apply behavior.

The marker has two effects: (a) a player-visible chip rendered by the
frontend and (b) a backend state flip — `agent.reveal_name(npc_key)`.
These tests focus on the parser + the apply path; the rendering is
exercised by frontend tsc.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Patch flag_modified so SimpleNamespace fakes (no SQLAlchemy state) work.
import sqlalchemy.orm.attributes as _sa_attrs  # noqa: E402

_sa_attrs.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]
import services.trpg_ic_markers as _ic_markers_mod  # noqa: E402

_ic_markers_mod.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]
import services.trpg_npc.agent as _npc_agent_mod  # noqa: E402

_npc_agent_mod.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]

from services.trpg_ic_markers import (  # noqa: E402
    apply_chatrpg_markers,
    parse_chatrpg_markers,
)


class NameRevealParseTests(unittest.TestCase):
    def test_parses_open_form_attrs(self):
        text = (
            'narration. [name_reveal npc_key="russ" name="拉斯·罗素"][/name_reveal] more.'
        )
        ext = parse_chatrpg_markers(text)
        self.assertEqual(len(ext.name_reveals), 1)
        item = ext.name_reveals[0]
        self.assertEqual(item["npc_key"], "russ")
        self.assertEqual(item["name"], "拉斯·罗素")
        self.assertEqual(item["reason"], "")

    def test_parses_block_body_as_reason(self):
        text = (
            '[name_reveal npc_key="russ" name="拉斯"]door tag visible[/name_reveal]'
        )
        ext = parse_chatrpg_markers(text)
        self.assertEqual(ext.name_reveals[0]["reason"], "door tag visible")

    def test_skips_when_no_npc_key(self):
        text = '[name_reveal name="拉斯"][/name_reveal]'
        ext = parse_chatrpg_markers(text)
        self.assertEqual(ext.name_reveals, [])

    def test_multiple_reveals_accumulate(self):
        text = (
            '[name_reveal npc_key="a" name="A"][/name_reveal]'
            '[name_reveal npc_key="b" name="B"]badge[/name_reveal]'
        )
        ext = parse_chatrpg_markers(text)
        self.assertEqual([r["npc_key"] for r in ext.name_reveals], ["a", "b"])

    def test_extraction_not_empty_when_only_reveal_present(self):
        ext = parse_chatrpg_markers('[name_reveal npc_key="x" name="X"][/name_reveal]')
        self.assertFalse(ext.is_empty())


class NameRevealApplyTests(unittest.TestCase):
    """Smoke-test `apply_chatrpg_markers` with a minimal session
    namespace + an NpcAgent-compatible memory_state. The agent flips
    `name_revealed=true` and also lifts `player_known_name` to the
    true name (mirrors `reveal_name`)."""

    def _session(self, *, name_revealed: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            id="s1",
            user_id="u1",
            character={},
            module_state={"scene": "scene_gas_station"},
            memory_state={
                "npcs": [{
                    "key": "russ",
                    "name": "拉斯",
                    "player_known_name": "加油站老板",
                    "name_revealed": name_revealed,
                    "role": "gas station owner",
                }],
            },
        )

    def test_apply_flips_name_revealed(self):
        session = self._session()
        ext = parse_chatrpg_markers(
            '[name_reveal npc_key="russ" name="拉斯"][/name_reveal]'
        )
        meta: dict = {}
        summary = apply_chatrpg_markers(session, ext, gm_message_metadata=meta)
        self.assertEqual(summary.get("name_reveals"), 1)
        npc = session.memory_state["npcs"][0]
        self.assertTrue(npc["name_revealed"])
        self.assertEqual(npc["player_known_name"], "拉斯")
        self.assertEqual(meta["name_reveals"][0]["flipped"], True)
        self.assertEqual(meta["name_reveals"][0]["npc_key"], "russ")

    def test_apply_idempotent_on_already_revealed(self):
        session = self._session(name_revealed=True)
        ext = parse_chatrpg_markers(
            '[name_reveal npc_key="russ" name="拉斯"][/name_reveal]'
        )
        meta: dict = {}
        summary = apply_chatrpg_markers(session, ext, gm_message_metadata=meta)
        self.assertEqual(summary.get("name_reveals"), 0)
        self.assertEqual(meta["name_reveals"][0]["flipped"], False)

    def test_apply_unknown_npc_key_is_recorded_but_no_flip(self):
        session = self._session()
        ext = parse_chatrpg_markers(
            '[name_reveal npc_key="ghost" name="Casper"][/name_reveal]'
        )
        meta: dict = {}
        summary = apply_chatrpg_markers(session, ext, gm_message_metadata=meta)
        self.assertEqual(summary.get("name_reveals"), 0)
        self.assertEqual(meta["name_reveals"][0]["flipped"], False)
        # Roster left untouched.
        self.assertFalse(session.memory_state["npcs"][0]["name_revealed"])


if __name__ == "__main__":
    unittest.main()
