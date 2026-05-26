"""Preprocess phase — dispatches to the right BP builder for the chosen mode.

GUIDE goes through build_bp_guide. IC and BREAK both go through build_bp_ic
(BREAK fills `IcContext.campaign_history_text`; IC fills the live-game fields).
Caller supplies `inputs.ic_context` for IC/BREAK; if missing, framework
substitutes an empty IcContext so the pipeline still runs (with degraded BP3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..bp import BpSnapshot, build_bp_guide, build_bp_ic
from ..models import (
    IcContext,
    LayeredPrompt,
    PromptMessage,
    TrpgServices,
    TurnInputs,
)
from ..modes import Mode, select_mode


@dataclass
class PreprocessOutput:
    mode: Mode
    bp_snapshot: BpSnapshot
    prompt_messages: list[PromptMessage]
    thinking_lines: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # IC builder fills this; GUIDE leaves it empty (no caching benefit on
    # short setup chats). When non-empty, the LlmAdapter routes through the
    # provider's cache-aware path.
    layered_prompt: LayeredPrompt | None = None


async def preprocess(
    inputs: TurnInputs, services: TrpgServices,
) -> PreprocessOutput:
    mode = select_mode(inputs.session_state, inputs.mode_hint)
    if mode == Mode.GUIDE:
        out = build_bp_guide(inputs, services)
        return PreprocessOutput(
            mode=mode,
            bp_snapshot=out.snapshot,
            prompt_messages=out.prompt_messages,
            thinking_lines=list(out.thinking_lines),
            metadata=dict(out.metadata),
        )
    # IC and BREAK
    ic_ctx = inputs.ic_context or IcContext()
    out_ic = build_bp_ic(inputs, services, ic_context=ic_ctx)
    return PreprocessOutput(
        mode=mode,
        bp_snapshot=out_ic.snapshot,
        prompt_messages=out_ic.prompt_messages,
        thinking_lines=list(out_ic.thinking_lines),
        metadata=dict(out_ic.metadata),
        layered_prompt=out_ic.layered_prompt,
    )
