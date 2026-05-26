"""`[debug]...[/debug]` tag helpers ported from chatlab.

A tester can scope test directives inside `[debug]…[/debug]` brackets in
their player message, e.g. ::

    我冲下楼梯，警枪压低指地。 [debug]触发 san_check 1d6 SAN loss[/debug]

The whole message (including the tags) is passed to the GM LLM. The
system prompt teaches the GM to read debug blocks as out-of-character
test injections — it should weave the directive into IC narration but
NOT auto-write character state unless the directive explicitly asks
for it. Persisted state writes (UPDATE_PC_PARAMS / UPDATE_NPC_PARAMS)
are gated by `should_block_debug_state_marker()` so a casual debug
event-trigger doesn't accidentally mutate the saved character.

The `force write` keyword family (or 强制写入 / 持久化 PC … in Chinese)
opts back IN — used for explicit "test cross-turn persistence" cases.

Mirrors `chatlab/backend/agents/trpg/phase_preprocess.py` lines 14-51.
"""

from __future__ import annotations

import re

_DEBUG_TAG_RE = re.compile(
    r"\[debug\](.*?)\[/debug\]",
    re.IGNORECASE | re.DOTALL,
)
_DEBUG_FORCE_STATE_WRITE_RE = re.compile(
    r"("
    r"update_pc_params|update_npc_params|"
    r"force\s+(write|persist|set|update)|forced\s+state|state[-_\s]?write|"
    r"强制(写入|更新|设置|持久化)|"
    r"测试.{0,12}(状态写入|参数写入|持久化)|"
    r"(写入|持久化).{0,8}(PC|NPC|角色|参数|状态)"
    r")",
    re.IGNORECASE,
)
_DEBUG_STATE_MARKER_TOOLS = {"update_pc_params", "update_npc_params"}


def has_debug_tag(message: str) -> bool:
    """True if the user message contains at least one [debug]...[/debug] block."""
    return bool(message) and bool(_DEBUG_TAG_RE.search(message))


def iter_debug_blocks(message: str) -> list[str]:
    """Return natural-language contents from all [debug]...[/debug] blocks."""
    if not message:
        return []
    return [m.group(1).strip() for m in _DEBUG_TAG_RE.finditer(message)]


def debug_allows_state_write(message: str) -> bool:
    """True only when debug explicitly asks to test forced state persistence."""
    return any(
        _DEBUG_FORCE_STATE_WRITE_RE.search(block or "")
        for block in iter_debug_blocks(message)
    )


def should_block_debug_state_marker(
    tool_name: str,
    player_message: str,
) -> bool:
    """Block model-emitted PC/NPC state writes during normal debug event tests.

    `tool_name` is the lowercased marker name (`update_pc_params` /
    `update_npc_params`). Returns True when the runtime should skip the
    state write because the player is debugging an EVENT (not a state-
    persistence test).
    """
    return (
        tool_name in _DEBUG_STATE_MARKER_TOOLS
        and has_debug_tag(player_message)
        and not debug_allows_state_write(player_message)
    )


# Section the chatlab system prompt uses to teach the GM what to do
# with debug blocks. We expose it as a constant so the chatrpg system
# prompt builder can paste it into its own assembly without forking
# the wording.
DEBUG_TAG_PROMPT_SECTION = """## Debug Mode (`[debug]…[/debug]`) — TESTER-ONLY DIRECTIVE

When the player message contains a `[debug]…[/debug]` block, treat that
block as an OUT-OF-CHARACTER test directive issued by the tester. The
text before / after the block is normal IC. Inside the block the tester
may name procedures, NPCs, or specific outcomes — these are
test-trigger hints, NOT mandates the player character knows about.

How to handle a debug directive:
- Acknowledge silently. Do NOT echo `[debug]` in your reply.
- Translate the directive into in-fiction events that produce the
  requested test condition. If the tester wrote
  `[debug]触发 san_check 1d6 SAN loss[/debug]`, narrate something the
  PC actually sees that justifies emitting the `[CHECK san_check ...]`
  marker — not "[OOC: forcing SAN check]".
- Emit the corresponding [CHECK ...] markers exactly as you would in
  organic IC play. The check engine resolves them; you don't roll dice
  yourself.
- DO NOT emit `[UPDATE_PC_PARAMS]` / `[UPDATE_NPC_PARAMS]` markers in
  response to a debug directive UNLESS the directive's text contains a
  forcing keyword like `force write`, `强制写入`, `持久化 PC`,
  `state-write`, etc. Default debug mode tests EVENTS, not state
  persistence; the runtime will silently drop param updates that arise
  from event-only debug runs.
- The tester intentionally telegraphs intent so you can build a clean
  test path. Stay in voice — the resulting narration must read like a
  real moment in the campaign, not like a unit-test scaffolding.

Examples
- Player: `我打开 1404 的门 [debug]让门后跳出畸形巨鼠群，触发 san_check[/debug]`
  → Narrate the door swinging open onto a writhing carpet of malformed
  rats; emit `[CHECK san_check 50 Regular]`. Do not write SAN to disk.
- Player: `[debug]force write PC HP=1 to test cross-turn persistence[/debug]`
  → Narrate a brief in-fiction reason (a sudden gunshot wound, a fall),
  then emit `[UPDATE_PC_PARAMS]{...HP:1...}` — the forcing keyword
  authorises the state write."""
