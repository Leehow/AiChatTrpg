"""IC-mode BP builder.

IC mode = the game is running. The GM is narrating, players are acting,
NPCs / scenes / dice / memory are all live state.

Unlike GUIDE, the framework does NOT compute IC runtime state itself —
chatlab's IC pipeline runs NpcStore / scene_runtime / time_tracker / dice_pool
during phase_preprocess, then hands the resolved facts to this builder via
`IcContext`. Framework only renders.

Builder produces:
  * BpSnapshot — for debug panel
  * list[PromptMessage] — system + history + user (no chatlab-specific
    GM_SYSTEM_PROMPT_V2 templates; caller weaves those in)
  * list[str] — thinking lines
  * Convenience text fragments matching the existing PreprocessResult shape
    (mandatory_content / memory_context / pc_npc_state / filtered_content)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..adapters.protocols import RulesetAdapter
from ..models import (
    IcContext,
    LayeredPrompt,
    Message,
    PromptMessage,
    RulesetData,
    SessionState,
    StableText,
    TrpgServices,
    TurnInputs,
)
from .snapshot import Bp1, Bp2, Bp3, BpSnapshot

IC_RECENT_MESSAGES = 5


@dataclass
class BpIcOutput:
    snapshot: BpSnapshot
    prompt_messages: list[PromptMessage]
    thinking_lines: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    # Structured fragments mapped onto chatlab's PreprocessResult shape:
    stable_text_block: str = ""        # → mandatory_content (BP1)
    memory_text_block: str = ""        # → memory_context (BP2 narrative + module chapter)
    pc_npc_text_block: str = ""        # → pc_npc_state (BP3 PC + active NPCs + inventory)
    rag_text_block: str = ""           # → filtered_content (BP3 retrieval hits)
    bp3_extras_block: str = ""         # presim, time, dice — caller decides where to inject
    history_messages: list[PromptMessage] = field(default_factory=list)
    user_message: str | None = None
    # Cache-aware projection: BP1/BP2/BP3 split as three text layers, history
    # + user_message as separate fields. Provider adapters consume this to
    # decide whether to use cache_control breakpoints (Claude), system + user
    # message pairs (DeepSeek/OpenAI), or systemInstruction + user prefix
    # (Gemini). Falls back to `prompt_messages` for clients without cache
    # support.
    layered_prompt: LayeredPrompt = field(default_factory=LayeredPrompt)


def build_bp_ic(
    inputs: TurnInputs,
    services: TrpgServices,
    *,
    ic_context: IcContext,
) -> BpIcOutput:
    """Pure builder. Caller pre-computes IcContext (chatlab does this in
    phase_preprocess via NpcStore / scene_runtime / etc.) and hands it in;
    framework just shapes it into BpSnapshot + prompt + thinking lines."""
    from ..modes import Mode

    state = inputs.session_state
    ruleset = inputs.ruleset
    adapter: RulesetAdapter = services.ruleset

    recent_history = _take_recent(state.chat_history, IC_RECENT_MESSAGES)
    stable_text = adapter.get_stable_text(ruleset, state, mode=Mode.IC)

    # ----- BP1
    bp1 = Bp1(
        stable_text=stable_text,
        ruleset_title=str(ruleset.book_title or ""),
        ruleset_world_mode=str(ruleset.world_mode or ""),
        module_title=(inputs.module.title if inputs.module else ""),
        module_text=(inputs.module.markdown if inputs.module else ""),
    )
    stable_text_block = _render_stable_text(stable_text).strip()

    # ----- BP2: live memory snapshot
    mem = state.memory_state if isinstance(state.memory_state, dict) else {}
    world_facts_raw = mem.get("world_facts")
    if isinstance(world_facts_raw, dict):
        world_facts = [
            {"key": str(k), "value": v}
            for k, v in world_facts_raw.items()
        ]
    elif isinstance(world_facts_raw, list):
        world_facts = list(world_facts_raw)
    else:
        world_facts = []

    bp2 = Bp2(
        scenes=list(mem.get("scenes") or []),
        npcs=list(mem.get("npcs") or []),
        plot_threads=list(mem.get("plot_threads") or []),
        world_facts=world_facts,
        narrative_summary=str(state.narrative_summary or ""),
        active_module_chapter=(
            {"name": ic_context.module_chapter_name,
             "text": ic_context.module_chapter_text}
            if ic_context.module_chapter_name else None
        ),
    )
    memory_text_block = _render_memory_block(
        bp2, campaign_history_text=ic_context.campaign_history_text,
    ).strip()

    # ----- BP3: per-turn live state
    pc = _extract_pc(state)
    pc_npc_text_block = _render_pc_npc_block(
        pc=pc,
        active_npcs=ic_context.active_npcs,
        inventory=list(mem.get("inventory") or []),
        player_message=inputs.user_message or "",
    ).strip()
    bp3_extras_block = _render_bp3_extras(ic_context).strip()
    rag_text_block = (ic_context.rag_text or "").strip()

    bp3 = Bp3(
        pc=pc,
        active_npcs=list(ic_context.active_npcs),
        time_context=ic_context.time_context,
        dice_pool_summary=ic_context.dice_pool_summary,
        rag_hits=_rag_text_to_hits(rag_text_block),
        user_message=inputs.user_message,
        chat_history_used=len(recent_history),
    )

    snapshot = BpSnapshot(bp1=bp1, bp2=bp2, bp3=bp3)

    # ----- layered prompt: stability-graded projection for cache-aware
    # providers. BP1 is byte-stable (rules + module), BP2 changes only when
    # memory snapshots refresh, BP3 churns every turn.
    stable_prefix = _assemble_stable_prefix(
        ruleset=ruleset,
        stable_text_block=stable_text_block,
        module_title=snapshot.bp1.module_title,
        module_text=snapshot.bp1.module_text,
    )
    layered_prompt = LayeredPrompt(
        stable_prefix=stable_prefix,
        semi_stable_context=memory_text_block,
        variable_suffix=_assemble_variable_suffix(
            pc_npc_text_block=pc_npc_text_block,
            bp3_extras_block=bp3_extras_block,
            rag_text_block=rag_text_block,
        ),
        history=_history_to_prompt_messages(recent_history),
        user_message=inputs.user_message or "",
    )

    # ----- prompt_messages: legacy single-system flatten. clients without
    # cache support consume this directly.
    prompt_messages = _flatten_layered_to_messages(layered_prompt)

    # ----- thinking lines
    thinking = list(snapshot.as_thinking_lines())
    if memory_text_block:
        thinking.append(f"[BP2 rendered] chars={len(memory_text_block)}")
    if pc_npc_text_block:
        thinking.append(f"[BP3 pc_npc] chars={len(pc_npc_text_block)}")
    if rag_text_block:
        thinking.append(f"[BP3 rag] chars={len(rag_text_block)}")
    if bp3_extras_block:
        thinking.append(f"[BP3 extras] chars={len(bp3_extras_block)}")
    sys_chars, user_chars, hist_chars = _measure_prompt(prompt_messages)
    total = sys_chars + user_chars + hist_chars
    thinking.append(
        f"[prompt] system={sys_chars} history={hist_chars} "
        f"user={user_chars} total={total} msgs={len(prompt_messages)}"
    )

    return BpIcOutput(
        snapshot=snapshot,
        prompt_messages=prompt_messages,
        thinking_lines=thinking,
        metadata={
            "recent_message_count": len(recent_history),
            "prompt_total_chars": total,
        },
        stable_text_block=stable_text_block,
        memory_text_block=memory_text_block,
        pc_npc_text_block=pc_npc_text_block,
        rag_text_block=rag_text_block,
        bp3_extras_block=bp3_extras_block,
        history_messages=_history_to_prompt_messages(recent_history),
        user_message=inputs.user_message,
        layered_prompt=layered_prompt,
    )


# ---------------------------------------------------------------------------
# rendering helpers


def _render_stable_text(st: StableText) -> str:
    parts: list[str] = []
    if st.resident_prompt:
        parts.append(f"## Resident Rules\n{st.resident_prompt}")
    if st.scene_guide:
        parts.append(f"## World & GM Style Guide\n{st.scene_guide}")
    if st.parameter_families:
        parts.append(f"## Parameter Families\n{st.parameter_families}")
    if st.core_rules_excerpt:
        parts.append(f"## Core Rules Excerpt\n{st.core_rules_excerpt}")
    return "\n\n".join(parts)


def _render_memory_block(bp2: Bp2, *, campaign_history_text: str = "") -> str:
    """Render BP2 (memory snapshot) as a single block. chatlab IC pipeline
    used to build this via build_memory_and_state — same shape preserved.
    BREAK mode passes campaign_history_text; IC leaves it empty."""
    parts: list[str] = []
    if bp2.narrative_summary:
        parts.append(f"## Narrative Summary\n{bp2.narrative_summary}")
    if campaign_history_text:
        parts.append(campaign_history_text)
    if bp2.active_module_chapter:
        ch = bp2.active_module_chapter
        title = ch.get("name") or "?"
        body = ch.get("text") or ""
        parts.append(f"## Active Module Chapter: {title}\n{body}")
    if bp2.scenes:
        parts.append(f"## Known Scenes\n```json\n{_json(bp2.scenes)}\n```")
    if bp2.plot_threads:
        parts.append(f"## Plot Threads\n```json\n{_json(bp2.plot_threads)}\n```")
    if bp2.world_facts:
        parts.append(f"## World Facts\n```json\n{_json(bp2.world_facts)}\n```")
    return "\n\n".join(parts)


def _render_pc_npc_block(
    *,
    pc: dict[str, Any] | None,
    active_npcs: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    player_message: str,
) -> str:
    """Render PC + active NPCs + inventory. Mirrors chatlab build_pc_npc_state
    shape so swapping is byte-equivalent (modulo PC inclusion which legacy
    chatlab does NOT do — see note in chatlab build_pc_npc_state)."""
    parts: list[str] = []
    if pc:
        parts.append(f"## PC\n```json\n{_json(pc)}\n```")
    if active_npcs:
        parts.append(f"## Active NPCs\n```json\n{_json(active_npcs)}\n```")
    inv_block = _render_inventory(inventory, player_message)
    if inv_block:
        parts.append(inv_block)
    return "\n\n".join(parts)


def _render_inventory(inventory: list[dict[str, Any]], player_message: str) -> str:
    """Match chatlab build_inventory_context behavior: cheap substring match
    surfaces full details for mentioned items, others as a names list."""
    if not inventory:
        return ""
    msg_lower = (player_message or "").lower()
    mentioned: list[dict[str, Any]] = []
    if msg_lower:
        for it in inventory:
            name = (it.get("name") or "").lower()
            if name and name in msg_lower:
                mentioned.append(it)
    lines = ["## Inventory"]
    for item in mentioned:
        props = item.get("properties") or {}
        prop_str = ", ".join(f"{k}: {v}" for k, v in props.items()) if props else ""
        detail = item.get("description", "") or ""
        if prop_str:
            detail = f"{detail} ({prop_str})" if detail else prop_str
        nm = item.get("name") or "?"
        lines.append(f"- **{nm}**: {detail}" if detail else f"- **{nm}**")
    names_only = [
        i.get("name", "?") for i in inventory if i not in mentioned
    ]
    if names_only:
        lines.append(f"Other items: {', '.join(names_only)}")
    return "\n".join(lines)


def _render_bp3_extras(ctx: IcContext) -> str:
    parts: list[str] = []
    if ctx.time_context:
        parts.append(f"## Time\n{ctx.time_context}")
    if ctx.dice_pool_summary:
        parts.append(f"## Dice Pool\n{ctx.dice_pool_summary}")
    if ctx.today_events:
        parts.append(f"## Today's Events\n```json\n{_json(ctx.today_events)}\n```")
    if ctx.gm_corrections:
        parts.append(f"## GM Corrections\n```json\n{_json(ctx.gm_corrections)}\n```")
    if ctx.player_tendencies:
        parts.append(f"## Player Tendencies\n{ctx.player_tendencies}")
    if ctx.narrative_variation_text:
        parts.append(ctx.narrative_variation_text)
    if ctx.extras_text:
        parts.append(ctx.extras_text)
    return "\n\n".join(parts)


def _assemble_stable_prefix(
    *,
    ruleset: RulesetData,
    stable_text_block: str,
    module_title: str,
    module_text: str,
) -> str:
    """BP1 — byte-stable across turns. Ruleset meta + scene/rules + module."""
    parts: list[str] = [_render_ruleset_meta(ruleset)]
    if stable_text_block:
        parts.append(stable_text_block)
    if module_text:
        parts.append(f"## Module: {module_title or '?'}\n{module_text}")
    return "\n\n".join(p for p in parts if p.strip())


def _assemble_variable_suffix(
    *,
    pc_npc_text_block: str,
    bp3_extras_block: str,
    rag_text_block: str,
) -> str:
    """BP3 — per-turn churn. PC + active NPCs + extras + retrieval hits."""
    parts: list[str] = []
    if pc_npc_text_block:
        parts.append(pc_npc_text_block)
    if bp3_extras_block:
        parts.append(bp3_extras_block)
    if rag_text_block:
        parts.append(f"## Retrieved Rules\n{rag_text_block}")
    return "\n\n".join(p for p in parts if p.strip())


def _flatten_layered_to_messages(layered: LayeredPrompt) -> list[PromptMessage]:
    """Collapse a LayeredPrompt back into the single-system shape that
    plain `stream_chat(messages)` consumers expect. Provider clients with
    cache support read `LayeredPrompt` directly; this is the fallback."""
    sys_parts = [
        layered.stable_prefix,
        layered.semi_stable_context,
        layered.variable_suffix,
    ]
    system = "\n\n".join(p for p in sys_parts if p and p.strip())
    msgs: list[PromptMessage] = []
    if system:
        msgs.append(PromptMessage(role="system", content=system))
    msgs.extend(layered.history)
    if layered.user_message and (
        not layered.history or layered.history[-1].content != layered.user_message
    ):
        msgs.append(PromptMessage(role="user", content=layered.user_message))
    return msgs


def _render_ruleset_meta(ruleset: RulesetData) -> str:
    title = ruleset.book_title or "?"
    mode = ruleset.world_mode or "?"
    return f"# Ruleset: {title}\nWorld mode: {mode}"


def _take_recent(history: list[Message], n: int) -> list[Message]:
    if not history or n <= 0:
        return []
    return list(history[-n:])


def _extract_pc(state: SessionState) -> dict[str, Any] | None:
    chars = state.characters or {}
    pc = chars.get("pc") if isinstance(chars, dict) else None
    return pc if isinstance(pc, dict) and pc else None


def _history_to_prompt_messages(history: list[Message]) -> list[PromptMessage]:
    out: list[PromptMessage] = []
    for m in history:
        if m.role == "user":
            out.append(PromptMessage(role="user", content=m.content))
        elif m.role == "gm":
            out.append(PromptMessage(role="assistant", content=m.content))
    return out


def _measure_prompt(messages: list[PromptMessage]) -> tuple[int, int, int]:
    sys_chars = 0
    user_chars = 0
    hist_chars = 0
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break
    for i, m in enumerate(messages):
        n = len(m.content)
        if m.role == "system":
            sys_chars += n
        elif i == last_user_idx:
            user_chars += n
        else:
            hist_chars += n
    return sys_chars, user_chars, hist_chars


def _rag_text_to_hits(rag_text: str) -> list[dict[str, Any]]:
    """Coarse adapter: collapse the rendered RAG block into a single hit dict
    so debug panels can count something. Real hit-level data lives in the
    RetrievalAdapter implementation."""
    if not rag_text:
        return []
    return [{"text": rag_text}]


def _json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(obj)
