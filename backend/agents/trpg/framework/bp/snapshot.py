"""BpSnapshot — the unified BP1/BP2/BP3 representation.

Every mode's builder produces this same shape. Difference is only in what
gets filled in. Two consumers:
  - as_thinking_lines(): debug panel rendering
  - as_prompt_messages(): what actually goes into the LLM call
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import PromptMessage, StableText


@dataclass
class Bp1:
    """Stable context: ruleset + module text. Constant across a session
    (until ruleset/module is swapped, which only happens in the setup wizard)."""

    stable_text: StableText
    module_title: str = ""
    module_text: str = ""
    ruleset_title: str = ""
    ruleset_world_mode: str = ""


@dataclass
class Bp2:
    """Memory snapshot. Empty in GUIDE; populated in IC."""

    scenes: list[dict[str, Any]] = field(default_factory=list)
    npcs: list[dict[str, Any]] = field(default_factory=list)
    plot_threads: list[dict[str, Any]] = field(default_factory=list)
    world_facts: list[dict[str, Any]] = field(default_factory=list)
    narrative_summary: str = ""
    active_module_chapter: dict[str, Any] | None = None


@dataclass
class Bp3:
    """Per-turn live state."""

    pc: dict[str, Any] | None = None
    active_npcs: list[dict[str, Any]] = field(default_factory=list)
    time_context: str = ""
    dice_pool_summary: str = ""
    rag_hits: list[dict[str, Any]] = field(default_factory=list)
    user_message: str | None = None
    chat_history_used: int = 0  # how many recent messages got into the prompt


@dataclass
class BpSnapshot:
    bp1: Bp1
    bp2: Bp2
    bp3: Bp3

    def as_thinking_lines(self) -> list[str]:
        """Debug-panel-friendly summary. One line per BP block, key=value
        fragments inside. Used by the right-rail Context tab and the inline
        chain-of-thought display.

        Format is stable across modes — guide / ic / break all produce the
        same shape so debug tooling can parse uniformly."""
        return [
            "[BP1 stable] " + " | ".join(_bp1_fragments(self.bp1)),
            "[BP2 memory] " + " | ".join(_bp2_fragments(self.bp2)),
            "[BP3 turn] " + " | ".join(_bp3_fragments(self.bp3)),
        ]

    def as_prompt_messages(self) -> list[PromptMessage]:
        """Reserved for a future default rendering. Builders currently produce
        their own prompt messages directly (see PreprocessOutput.prompt_messages),
        so this method has no callers yet — keeping it un-implemented until we
        decide whether the framework needs a canonical fallback."""
        raise NotImplementedError(
            "BpSnapshot.as_prompt_messages: builders produce prompt messages "
            "directly via PreprocessOutput.prompt_messages."
        )


def _bp1_fragments(bp1: Bp1) -> list[str]:
    parts = [f"ruleset={bp1.ruleset_title or '?'}"]
    st = bp1.stable_text
    if st.resident_prompt:
        parts.append(f"resident={len(st.resident_prompt)}")
    if st.scene_guide:
        parts.append(f"scene_guide={len(st.scene_guide)}")
    if st.chargen_pack:
        parts.append(f"chargen={len(st.chargen_pack)}")
    if st.parameter_families:
        parts.append(f"params={len(st.parameter_families)}")
    if st.core_rules_excerpt:
        parts.append(f"core_rules={len(st.core_rules_excerpt)}")
    if bp1.module_text:
        title = bp1.module_title or "?"
        parts.append(f"module={title}({len(bp1.module_text)})")
    else:
        parts.append("module=none")
    return parts


def _bp2_fragments(bp2: Bp2) -> list[str]:
    parts = [
        f"scenes={len(bp2.scenes)}",
        f"npcs={len(bp2.npcs)}",
        f"plots={len(bp2.plot_threads)}",
        f"facts={len(bp2.world_facts)}",
    ]
    if bp2.narrative_summary:
        parts.append(f"summary={len(bp2.narrative_summary)}")
    if bp2.active_module_chapter:
        parts.append("module_chapter=present")
    return parts


def _bp3_fragments(bp3: Bp3) -> list[str]:
    parts = [
        f"chat_used={bp3.chat_history_used}",
        f"pc={'present' if bp3.pc else 'none'}",
    ]
    if bp3.active_npcs:
        parts.append(f"npcs_active={len(bp3.active_npcs)}")
    if bp3.time_context:
        parts.append(f"time={bp3.time_context}")
    if bp3.dice_pool_summary:
        parts.append(f"dice_pool={bp3.dice_pool_summary}")
    if bp3.rag_hits:
        parts.append(f"rag_hits={len(bp3.rag_hits)}")
    if bp3.user_message is not None:
        parts.append(f"user_chars={len(bp3.user_message)}")
    return parts
