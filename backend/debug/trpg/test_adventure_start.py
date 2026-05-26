from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orm.models import GameSession, ParsedModule
from services.trpg_adventure_start import (
    activate_adventure_start,
    active_module_chapter_from_state,
    build_adventure_start_options,
)


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def make_module() -> ParsedModule:
    return ParsedModule(
        id="mod1",
        owner_id="user1",
        filename="Haunted Road.md",
        markdown=(
            "# Crossroads\n"
            "Alice: a roadside informant.\n"
            "The PC arrives beside the old mile marker.\n"
            "# Farmhouse\n"
            "Bob: the missing farmer.\n"
        ),
        semantic_status="done",
        semantic_structure={
            "anchor_type": "location",
            "progression": "sandbox",
            "selection_rule": "Start wherever the player chooses.",
            "playable_units": [
                {
                    "title": "Crossroads",
                    "kind": "location",
                    "summary": "A cold roadside opening.",
                    "line_start": 1,
                    "line_end": 3,
                },
                {
                    "title": "Farmhouse",
                    "kind": "location",
                    "summary": "The first enclosed investigation scene.",
                    "line_start": 4,
                    "line_end": 5,
                },
            ],
        },
        appendix_index={
            "entries": [
                {"name": "Alice", "type": "npc", "brief": "A roadside informant."},
                {"name": "Bob", "type": "npc", "brief": "The missing farmer."},
            ]
        },
    )


def case_options_expose_playable_units() -> None:
    options = build_adventure_start_options(make_module())
    assert_true("has module", options["has_module"] is True)
    assert_true("needs selection", options["needs_selection"] is True)
    assert_true("anchor type", options["anchor_type"] == "location")
    assert_true("two units", len(options["units"]) == 2)


def case_activate_selected_unit_initializes_scene_and_npcs() -> None:
    session = GameSession(id="sess1", user_id="user1")
    session.setup_state = {"step": 2, "module_id": "mod1", "completed": False}
    module = make_module()
    result = activate_adventure_start(session, module, unit_index=0)

    assert_true("mode module", result["mode"] == "module")
    assert_true("setup completed", session.setup_state["completed"] is True)
    assert_true("scene set", session.module_state["scene"] == "crossroads")
    assert_true(
        "active module text sliced",
        "old mile marker" in session.module_state["active_module_content"]["raw_content"],
    )
    assert_true(
        "unselected unit omitted",
        "missing farmer" not in session.module_state["active_module_content"]["raw_content"],
    )
    npcs = session.memory_state["npcs"]
    assert_true("initial npc added", len(npcs) == 1, repr(npcs))
    assert_true("npc scene stamped", npcs[0]["last_seen_scene"] == "crossroads")


def case_activate_freeform_initializes_clock() -> None:
    session = GameSession(id="sess-freeform", user_id="user1")
    session.setup_state = {"step": 1, "module_id": "__freeform__", "completed": False}
    result = activate_adventure_start(session, None)

    assert_true("mode freeform", result["mode"] == "freeform")
    assert_true("freeform setup completed", session.setup_state["completed"] is True)
    assert_true("freeform day initialized", session.module_state["day_count"] == 1)
    assert_true("freeform clock initialized", session.module_state["in_game_time"] == "09:00")


def case_ic_context_reads_active_module_chapter() -> None:
    session = GameSession(id="sess1", user_id="user1")
    activate_adventure_start(session, make_module(), unit_index=1)
    name, text = active_module_chapter_from_state(session.module_state)
    assert_true("chapter name", name == "Farmhouse")
    assert_true("chapter text", "missing farmer" in text)


if __name__ == "__main__":
    case_options_expose_playable_units()
    case_activate_selected_unit_initializes_scene_and_npcs()
    case_activate_freeform_initializes_clock()
    case_ic_context_reads_active_module_chapter()
    print("All adventure start cases passed.")
