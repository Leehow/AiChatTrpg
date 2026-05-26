"""Guide-mode BP builder.

Guide mode = character setup before play starts. The LLM acts as a writing
companion that helps the player crystallize a character through dialogue.

Inputs the builder cares about:
  * Stable ruleset slices (resident rules / scene guide / chargen pack /
    parameter families / core rules excerpt) — via RulesetAdapter
  * Optional module text (where the campaign will start)
  * Recent chat history for multi-turn setup conversation
  * Current PC draft (if the player is iterating on an existing draft)
  * Current user message
  * Per-turn variable nudges (auto-create / batch / arc-aware) — delegated
    to RulesetAdapter so chatlab-private logic stays out of framework

Builder produces:
  * BpSnapshot — for debug panel
  * list[PromptMessage] — system + user(+chat) for the LLM call
  * list[str] — thinking lines (by default = BpSnapshot.as_thinking_lines)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..adapters.protocols import RulesetAdapter
from ..models import (
    Message,
    PromptMessage,
    RulesetData,
    SessionState,
    StableText,
    TrpgServices,
    TurnInputs,
)
from .snapshot import Bp1, Bp2, Bp3, BpSnapshot

# How many of the most recent chat messages to inject as multi-turn context.
# Matches the existing chatlab guide-mode behavior in phase_preprocess.
GUIDE_RECENT_MESSAGES = 6


@dataclass
class BpGuideOutput:
    snapshot: BpSnapshot
    prompt_messages: list[PromptMessage]
    thinking_lines: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    # Convenience structured fragments. Projects that want to assemble the
    # prompt their own way (e.g. chatlab IC pipeline appending GM_SYSTEM_PROMPT
    # templates) should consume these instead of `prompt_messages` and weave
    # in their own scaffolding.
    stable_text_block: str = ""        # mirrors legacy `mandatory_content`
    variable_text_block: str = ""      # mirrors legacy `guide_variable_rules`
    pc_block: str = ""                 # mirrors legacy `pc_npc_state` (PC-only)
    history_messages: list[PromptMessage] = field(default_factory=list)
    user_message: str | None = None


def build_bp_guide(inputs: TurnInputs, services: TrpgServices) -> BpGuideOutput:
    """Pure(-ish) builder: only side effect is calling RulesetAdapter methods.
    No DB access, no LLM calls, no IO. Safe to unit-test with a stub adapter."""
    state = inputs.session_state
    ruleset = inputs.ruleset
    adapter: RulesetAdapter = services.ruleset

    recent_history = _take_recent(state.chat_history, GUIDE_RECENT_MESSAGES)
    stable_text = adapter.get_stable_text(ruleset, state, mode=_GUIDE_MODE)
    variable_text = adapter.get_guide_variable_text(
        ruleset, state,
        message=inputs.user_message,
        recent_history=recent_history,
    )

    bp1 = Bp1(
        stable_text=stable_text,
        ruleset_title=str(ruleset.book_title or ""),
        ruleset_world_mode=str(ruleset.world_mode or ""),
        module_title=(inputs.module.title if inputs.module else ""),
        module_text=(inputs.module.markdown if inputs.module else ""),
    )
    bp2 = Bp2()  # guide mode never carries memory
    bp3 = _build_bp3(state, recent_history, inputs.user_message)
    snapshot = BpSnapshot(bp1=bp1, bp2=bp2, bp3=bp3)

    stable_text_block = _render_stable_text(snapshot.bp1.stable_text).strip()
    pc_block = _render_pc_block(snapshot.bp3.pc)
    variable_text_block = (variable_text or "").strip()
    history_messages = _history_to_prompt_messages(recent_history)

    prompt_messages = _render_prompt(
        snapshot, ruleset, state, recent_history,
        user_message=inputs.user_message,
        variable_text=variable_text,
    )

    thinking = list(snapshot.as_thinking_lines())
    if variable_text:
        thinking.append(f"[BP1 variable] chars={len(variable_text)}")
    sys_chars, user_chars, hist_chars = _measure_prompt(prompt_messages)
    total = sys_chars + user_chars + hist_chars
    thinking.append(
        f"[prompt] system={sys_chars} history={hist_chars} "
        f"user={user_chars} total={total} msgs={len(prompt_messages)}"
    )

    return BpGuideOutput(
        snapshot=snapshot,
        prompt_messages=prompt_messages,
        thinking_lines=thinking,
        metadata={
            "recent_message_count": len(recent_history),
            "prompt_total_chars": total,
        },
        stable_text_block=stable_text_block,
        variable_text_block=variable_text_block,
        pc_block=pc_block,
        history_messages=history_messages,
        user_message=inputs.user_message,
    )


def _measure_prompt(messages: list[PromptMessage]) -> tuple[int, int, int]:
    """Return (system_chars, user_chars, history_chars).

    The "fresh" user message is the last user-role entry; all earlier entries
    (whatever role) are counted as history. system messages are kept separate."""
    system_chars = 0
    user_chars = 0
    history_chars = 0
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break
    for i, m in enumerate(messages):
        n = len(m.content)
        if m.role == "system":
            system_chars += n
        elif i == last_user_idx:
            user_chars += n
        else:
            history_chars += n
    return system_chars, user_chars, history_chars


# ---------------------------------------------------------------------------
# internals


# Avoid importing Mode at module top to keep this file's imports tight.
# Resolved on first call.
_GUIDE_MODE = None


def _resolve_guide_mode():
    global _GUIDE_MODE
    if _GUIDE_MODE is None:
        from ..modes import Mode
        _GUIDE_MODE = Mode.GUIDE
    return _GUIDE_MODE


# Initialize at import time — keeps adapter signature simple.
_GUIDE_MODE = _resolve_guide_mode()


def _take_recent(history: list[Message], n: int) -> list[Message]:
    if not history:
        return []
    if n <= 0:
        return []
    return list(history[-n:])


def _build_bp3(
    state: SessionState, recent: list[Message], user_message: str | None,
) -> Bp3:
    pc = _extract_pc(state)
    return Bp3(
        pc=pc,
        active_npcs=[],          # guide mode never has live NPCs
        time_context="",         # game clock not started
        dice_pool_summary="",    # no dice in setup
        rag_hits=[],             # retrieval handled in IC mode only for now
        user_message=user_message,
        chat_history_used=len(recent),
    )


def _extract_pc(state: SessionState) -> dict[str, Any] | None:
    chars = state.characters or {}
    pc = chars.get("pc") if isinstance(chars, dict) else None
    if isinstance(pc, dict) and pc:
        return pc
    return None


def _render_prompt(
    snapshot: BpSnapshot,
    ruleset: RulesetData,
    state: SessionState,
    recent_history: list[Message],
    *,
    user_message: str | None,
    variable_text: str,
) -> list[PromptMessage]:
    """Compose the LLM messages from the snapshot + per-turn variables."""
    sys_parts: list[str] = []
    sys_parts.append(_render_ruleset_meta(ruleset))
    sys_parts.append(_render_stable_text(snapshot.bp1.stable_text))
    if snapshot.bp1.module_text:
        sys_parts.append(
            f"## Module Context: {snapshot.bp1.module_title or '?'}\n"
            f"{snapshot.bp1.module_text}"
        )
    if variable_text.strip():
        sys_parts.append(variable_text.strip())
    pc_block = _render_pc_block(snapshot.bp3.pc)
    if pc_block:
        sys_parts.append(pc_block)
    notes_block = _render_player_notes(state.player_notes)
    if notes_block:
        sys_parts.append(notes_block)

    system = "\n\n".join(p for p in sys_parts if p.strip())

    msgs: list[PromptMessage] = [PromptMessage(role="system", content=system)]
    # Multi-turn setup conversation: replay the recent history as alternating
    # user/assistant turns (excluding the just-sent user_message — caller
    # decides whether to include it in chat_history before invoking).
    for m in recent_history:
        if m.role == "user":
            msgs.append(PromptMessage(role="user", content=m.content))
        elif m.role == "gm":
            msgs.append(PromptMessage(role="assistant", content=m.content))
        # system / dice messages from history are skipped — they don't belong in chat replay
    if user_message is not None and (
        not recent_history or recent_history[-1].content != user_message
    ):
        msgs.append(PromptMessage(role="user", content=user_message))
    return msgs


def _render_ruleset_meta(ruleset: RulesetData) -> str:
    title = ruleset.book_title or "?"
    mode = ruleset.world_mode or "?"
    return f"# Ruleset: {title}\nWorld mode: {mode}"


def _render_stable_text(st: StableText) -> str:
    parts: list[str] = []
    if st.resident_prompt:
        parts.append(f"## Resident Rules\n{st.resident_prompt}")
    if st.scene_guide:
        parts.append(f"## World & GM Style Guide\n{st.scene_guide}")
    if st.chargen_pack:
        # Match legacy chatlab `_build_guide_character_creation_block` —
        # it strips the pack before insertion, callers depend on that shape.
        parts.append(
            "## Character Template + Creation Workflow\n"
            f"{st.chargen_pack.strip()}"
        )
    if st.parameter_families:
        parts.append(f"## Parameter Families\n{st.parameter_families}")
    if st.core_rules_excerpt:
        parts.append(f"## Core Rules Excerpt\n{st.core_rules_excerpt}")
    return "\n\n".join(parts)


def _history_to_prompt_messages(history: list[Message]) -> list[PromptMessage]:
    """Replay framework Messages as alternating user/assistant PromptMessages.
    GM messages map to assistant; system / dice messages are skipped."""
    out: list[PromptMessage] = []
    for m in history:
        if m.role == "user":
            out.append(PromptMessage(role="user", content=m.content))
        elif m.role == "gm":
            out.append(PromptMessage(role="assistant", content=m.content))
    return out


def _render_pc_block(pc: dict[str, Any] | None) -> str:
    if not pc:
        return ""
    try:
        body = json.dumps(pc, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        body = str(pc)
    return f"## Current PC Draft\n```json\n{body}\n```"


def _render_player_notes(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return ""
    lines = ["## Player Notes"]
    for n in notes[-12:]:
        if not isinstance(n, dict):
            continue
        content = (n.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- {content}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
