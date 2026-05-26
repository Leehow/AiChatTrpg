"""[debug]…[/debug] tag helper tests.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_debug_tag.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trpg_debug_tag import (  # noqa: E402
    has_debug_tag,
    iter_debug_blocks,
    debug_allows_state_write,
    should_block_debug_state_marker,
)


def assert_eq(label: str, got, want):
    if got != want:
        print(f"FAIL: {label}\n  got:  {got!r}\n  want: {want!r}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_true(label: str, cond: bool):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"OK: {label}")


def main():
    # has_debug_tag
    assert_eq("no tag", has_debug_tag("我冲下去开门"), False)
    assert_eq(
        "has tag",
        has_debug_tag("我开枪 [debug]触发 san_check[/debug]"),
        True,
    )
    assert_eq("case-insensitive", has_debug_tag("[DEBUG]x[/DEBUG]"), True)
    assert_eq("multiline", has_debug_tag("[debug]line1\nline2[/debug]"), True)

    # iter_debug_blocks
    assert_eq("no tag → []", iter_debug_blocks("hello"), [])
    assert_eq(
        "single block content",
        iter_debug_blocks("a [debug] hi [/debug] b"),
        ["hi"],
    )
    assert_eq(
        "two blocks",
        iter_debug_blocks("[debug]one[/debug] mid [debug]two[/debug]"),
        ["one", "two"],
    )

    # debug_allows_state_write — default OFF
    assert_eq(
        "event-only debug, no force",
        debug_allows_state_write("[debug]触发 san_check[/debug]"),
        False,
    )
    assert_eq(
        "english force write",
        debug_allows_state_write("[debug]force write PC HP=1[/debug]"),
        True,
    )
    assert_eq(
        "chinese 强制写入",
        debug_allows_state_write("[debug]强制写入 PC HP=1[/debug]"),
        True,
    )
    assert_eq(
        "持久化 keyword",
        debug_allows_state_write("[debug]测试 PC 持久化 HP[/debug]"),
        True,
    )
    assert_eq(
        "no debug, no force",
        debug_allows_state_write("force write nothing"),
        False,
    )

    # should_block_debug_state_marker — combined logic
    msg_event = "我开枪 [debug]触发 san_check[/debug]"
    msg_force = "[debug]force write PC HP=1 to test persistence[/debug]"
    msg_no_debug = "我开枪"
    assert_eq(
        "block UPDATE_PC_PARAMS during event-only debug",
        should_block_debug_state_marker("update_pc_params", msg_event),
        True,
    )
    assert_eq(
        "do NOT block when force-write keyword present",
        should_block_debug_state_marker("update_pc_params", msg_force),
        False,
    )
    assert_eq(
        "do NOT block when no debug tag at all",
        should_block_debug_state_marker("update_pc_params", msg_no_debug),
        False,
    )
    assert_eq(
        "irrelevant tool name → never blocked",
        should_block_debug_state_marker("create_npc", msg_event),
        False,
    )
    assert_eq(
        "block UPDATE_NPC_PARAMS too",
        should_block_debug_state_marker("update_npc_params", msg_event),
        True,
    )

    # Edge cases
    assert_eq(
        "empty string everywhere",
        should_block_debug_state_marker("update_pc_params", ""),
        False,
    )
    assert_eq("None-ish handling", has_debug_tag(""), False)

    print("\nAll debug-tag tests passed.")


if __name__ == "__main__":
    main()
