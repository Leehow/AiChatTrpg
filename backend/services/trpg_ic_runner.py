"""IC (in-character) turn runner — chatrpg's bridge into the framework.

Once setup finishes (`session.character` set, `setup_state.completed=True`),
the game enters IC mode. This module:

  * Builds a `ChatrpgLlmAdapter` that satisfies the framework's `LlmAdapter`
    protocol by wrapping chatrpg's existing `build_client` provider router.
  * Loads the unified message timeline from the `messages` table (any phase).
  * Calls `run_trpg_turn` and forwards events as SSE-friendly dicts.
  * Persists the user message + GM reply (phase=ic) and applies the framework's
    `SessionStateDiff` to `session.memory_state` / `module_state` /
    `dice_history`. The framework computes everything in-memory; this module
    is the single place that touches the ORM.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("chatrpg.trpg")

from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.framework import FeatureFlags, ModelConfig
from orm.models import GameSession, ParsedModule, Ruleset
from services.character_creator import _resolve_model
from services.trpg_ic.framework_stream import (
    FrameworkStreamResult,
    stream_framework_events,
)
from services.trpg_ic.llm_adapter import ChatrpgLlmAdapter
from services.trpg_ic.messages import (
    _IC_PHASE,
    _load_recent_messages,
    _save_message,
)
from services.trpg_ic.post_state import (
    PostStateResult,
    stream_post_state_phase,
)
from services.trpg_ic.post_turn import (
    PostTurnResult,
    stream_post_turn_phase,
)
from services.trpg_ic.state_diff import (
    _apply_npc_memory_update,
    _apply_npc_ops,
    _ensure_memory_buckets,
    _runtime_check_spec_for_ruleset,
)
from services.trpg_npc.assets import spawn_npc_portrait_task
from services.trpg_pending_checks import resolve_all_pending_in_session
from services.trpg_scene_runtime import (
    build_ic_context,
    build_ic_context_table_first,
)

_RESOLVE_INTENT = "resolve"
# When the player clicks "投出" the synthetic input that gets fed to the
# framework. Not persisted as a chat message — used purely as the user-turn
# input slot the GM model consumes for this continuation.
#
# The hint is strict because we observed in early testing that the GM,
# given freedom, would write aftermath that contradicted the dice block —
# e.g. dice said "双方僵持" (stalemate) but GM described the PC's blade
# biting in. The instruction below forces the model to ground every bit
# of consequence prose in what the [dice] block actually says: who hit,
# who missed, whose tier was higher, whether anyone took damage, and
# (for [CONTEST]) the outcome verb.
_RESOLVE_USER_HINT = (
    "（系统提示：上一回合发生了一次自动结算的检定 / 对抗，结果在以上最近的 [dice] 块里。"
    "请严格按那个 [dice] 块的判定叙事，不得编造未发生的命中、伤害或胜负。\n"
    "1. 若 [dice] 写『双方僵持』或没人成功，不能描写命中 / 流血 / 击倒，"
    "只能写僵持画面（喘息、对峙、武器没入空气、刀尖擦过衣布等）。\n"
    "2. 若 [dice] 写『攻击方获胜』，按伤害公式描写命中后果；"
    "若末尾说『需提供伤害骰值后才能结算』则只描写命中迹象但不写具体血量损失。\n"
    "3. 若 [dice] 写『防守方获胜』或反击成功，描写攻击者反受伤 / 失衡 / 武器脱手等。\n"
    "4. 大成功 / 极难成功 → 后果明显比常规成功更彻底；大失败 → 比常规失败更糟。\n"
    "5. 不要重复发出同一个 [CHECK] 或 [CONTEST]，不再次掷骰，不复述骰值数字。\n"
    "6. 推动剧情往前走半步：NPC 反应 / 环境响应 / 新决断点。）"
)

def _is_discovery_event(event_type: str) -> bool:
    kind = str(event_type or "").upper()
    return any(
        token in kind
        for token in ("CLUE", "DISCOVER", "LEARN", "REVEAL", "WORLD_FACT")
    )


# ---------------------------------------------------------------------------
# Public SSE generator


async def stream_ic_turn(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    user_message: str,
    *,
    intent: str | None = None,
    pending_check_id: str | None = None,
    roll_result: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """One IC turn: persist user → run framework → stream events → persist
    GM reply + state diff. Compatible with `_stream_with_fresh_db` from
    `routes.sessions` (yields plain dicts, no `data:` prefix).

    ``intent="resolve"``: the player clicked "投出" on a pending check.
    Skip user-message persistence, resolve the selected latest-GM
    ``[pending_check ...]`` placeholder (using `roll_result` when supplied),
    save `role=dice` rows + replace placeholder text, then run the framework
    with a synthetic continuation hint so the GM narrates the consequence.
    Default ``intent`` (None) is the standard player-typed turn."""

    is_resolve = intent == _RESOLVE_INTENT
    text = (user_message or "").strip()
    if not is_resolve and not text:
        raise ValueError("message is required")

    user_message_id: str | None = None
    if is_resolve:
        check_spec_for_resolve = _runtime_check_spec_for_ruleset(ruleset)
        try:
            resolved = await resolve_all_pending_in_session(
                db,
                session,
                check_spec_for_resolve,
                pending_check_id=pending_check_id,
                auto_roll=roll_result,
            )
        except Exception as exc:  # pragma: no cover — defensive
            yield {
                "type": "error",
                "content": f"resolve failed: {exc}",
                "exc_type": type(exc).__name__,
            }
            return
        if not resolved:
            # Nothing to resolve — fall back to a normal continuation. The
            # synthetic hint still lets the GM continue the scene.
            pass
        else:
            for entry in resolved:
                yield {
                    "type": "side_effect",
                    "kind": "pending_check_resolved",
                    "payload": entry,
                }
        await db.commit()
        await db.refresh(session)
        # The framework still expects a non-empty user_message; use the
        # hint as that input slot. It is NOT persisted as a chat row.
        text = _RESOLVE_USER_HINT
    else:
        # Persist user msg first so a crashing LLM still leaves the message
        # in the timeline. Later we can de-dup if needed; for now this
        # matches chatlab's pattern.
        user_msg = await _save_message(db, session.id, "user", text, session=session)
        user_message_id = user_msg.id if user_msg is not None else None
        await db.commit()
        await db.refresh(session)

    chat_history = await _load_recent_messages(db, session.id)

    parsed_module: ParsedModule | None = None
    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    module_id = str(setup.get("module_id") or "")
    if module_id and module_id != "__freeform__":
        parsed_module = await db.get(ParsedModule, module_id)

    provider, model_name, api_key, base_url = await _resolve_model(db)
    llm = ChatrpgLlmAdapter(
        provider=provider, model=model_name,
        api_key=api_key, base_url=base_url, temperature=0.7,
    )

    turn_id_hint = int(session.last_summarized_msg_count or 0) + len(chat_history)
    turn_marker = f"turn_{max(1, turn_id_hint)}"
    # Build per-turn IcContext: filters memory_state.npcs[] by current scene,
    # runs the foreground NPC Runtime V2 beat-plan adapter, and renders only
    # prompt-safe active NPC fields to the GM. Phase 6 now tries a direct
    # table-backed pre-turn first, with JSON fallback.
    npc_runtime_read: dict[str, Any] = {}
    try:
        ic_context, npc_runtime_read = await build_ic_context_table_first(
            db,
            session,
            player_text=text,
            turn_id=max(1, turn_id_hint),
        )
    except Exception as _table_context_exc:
        npc_runtime_read = {
            "source": "json_fallback",
            "error": str(_table_context_exc),
        }
        ic_context = build_ic_context(
            session,
            player_text=text,
            turn_id=max(1, turn_id_hint),
        )

    from services.trpg_framework_adapter import (
        make_chatrpg_inputs, make_chatrpg_services,
    )
    inputs = make_chatrpg_inputs(
        orm_session=session,
        orm_ruleset=ruleset,
        parsed_module=parsed_module,
        user_message=text,
        model=ModelConfig(
            provider=provider, model=model_name, temperature=0.7,
            api_key=api_key, base_url=base_url,
        ),
        chat_history=chat_history,
        flags=FeatureFlags(enable_multimedia=False, enable_retrieval=False),
        ic_context=ic_context,
    )
    services = make_chatrpg_services(llm=llm)

    metadata_payload: dict[str, Any] = {"trpg_mode": "ic"}
    if npc_runtime_read:
        metadata_payload["npc_runtime_read"] = npc_runtime_read
    yield {"type": "metadata", "metadata": metadata_payload}

    framework_result = FrameworkStreamResult()
    async for ev in stream_framework_events(
        inputs=inputs,
        services=services,
        session=session,
        ruleset=ruleset,
        ic_context=ic_context,
        provider=provider,
        model_name=model_name,
        user_message_id=user_message_id,
        turn_id_hint=turn_id_hint,
        turn_marker=turn_marker,
        result=framework_result,
    ):
        yield ev
    if framework_result.empty_reply:
        return

    post_state_result = PostStateResult()
    async for ev in stream_post_state_phase(
        db=db,
        session=session,
        text=text,
        framework_result=framework_result,
        npc_runtime_read=npc_runtime_read,
        provider=provider,
        model_name=model_name,
        turn_id_hint=turn_id_hint,
        turn_marker=turn_marker,
        result=post_state_result,
    ):
        yield ev

    assistant_text = post_state_result.assistant_text
    diff_summary = post_state_result.diff_summary
    extension = post_state_result.extension
    extension_summary = post_state_result.extension_summary
    gm_meta = post_state_result.gm_meta
    portrait_task_keys = post_state_result.portrait_task_keys
    npc_post_visible_work = post_state_result.npc_post_visible_work
    gm_message = post_state_result.gm_message
    thinking_lines = framework_result.thinking_lines
    parsed_markers = framework_result.parsed_markers
    structured_parse = framework_result.structured_parse

    # `[SEARCH_RULES ...]` markers in the GM reply: run the lookup against
    # the active ruleset, persist each result as its own `role=system`
    # message right after the GM bubble. Next IC turn's `_load_recent_messages`
    # will pick these up so the GM sees the rule excerpt verbatim and can
    # cite or apply it. Errors are surfaced inline so the GM also gets a
    # legible "no match" explanation rather than silent absence.
    if extension.search_rules_queries:
        # Wave 3: ruleset lookup runs through the grep retrieval ReAct
        # agent (chatlab port). The agent issues bilingual keyword variants
        # via grep_search and reads the most promising source(s) before
        # returning the canonical excerpt. This replaces the single-pass
        # keyword search that couldn't bridge English PC equipment names
        # ("switchblade") to Chinese ruleset entries ("折刀").
        from services.trpg_grep_search import grep_search_ruleset

        parsed_v6 = ruleset.parsed_v6 if isinstance(getattr(ruleset, "parsed_v6", None), dict) else {}
        for req in extension.search_rules_queries:
            try:
                body, hit_count = await grep_search_ruleset(
                    parsed_v6=parsed_v6,
                    req=req,
                    model=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    provider=provider,
                    recent_messages=chat_history,
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("[SEARCH_RULES] lookup failed: %s", exc, exc_info=True)
                continue
            if not body:
                continue
            label = (
                req.get("query")
                or req.get("package_id")
                or req.get("family_id")
                or req.get("entry")
                or ""
            )
            header = f"## Rule lookup — `{label}`" if label else "## Rule lookup"
            # The agent already prepends its own heading; add the
            # GM-supplied label on top so the chat row is identifiable.
            await _save_message(
                db, session.id, "system",
                f"{header}\n\n{body}",
                metadata={
                    "phase": _IC_PHASE,
                    "source": "search_rules",
                    "query": req.get("query") or "",
                    "package_id": req.get("package_id"),
                    "family_id": req.get("family_id"),
                    "entry": req.get("entry"),
                    "hit_count": hit_count,
                    "retrieval": "grep_agent",
                },
                session=session,
            )
            yield {
                "type": "side_effect",
                "kind": "search_rules_resolved",
                "payload": {
                    "query": req.get("query") or "",
                    "package_id": req.get("package_id"),
                    "family_id": req.get("family_id"),
                    "entry": req.get("entry"),
                    "hit_count": hit_count,
                },
            }

    post_turn_result = PostTurnResult()
    async for ev in stream_post_turn_phase(
        db=db,
        session=session,
        text=text,
        framework_result=framework_result,
        post_state_result=post_state_result,
        npc_runtime_read=npc_runtime_read,
        llm=llm,
        provider=provider,
        model_name=model_name,
        turn_marker=turn_marker,
        result=post_turn_result,
    ):
        yield ev

    auto_summary = post_turn_result.auto_summary
    compression = post_turn_result.compression

    setup_state = (
        dict(session.setup_state)
        if isinstance(session.setup_state, dict) else {}
    )
    setup_state["game_started"] = True
    session.setup_state = setup_state
    session.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session)

    gm_message_id = str(gm_message.id) if gm_message is not None else ""
    background_tasks: list[asyncio.Task] = []
    try:
        from services.trpg_npc.post_visible_worker import spawn_npc_post_visible_work

        post_visible_task = spawn_npc_post_visible_work(
            session_id=str(session.id),
            user_id=str(session.user_id),
            player_text=text,
            gm_reply=assistant_text,
            turn_id=max(1, turn_id_hint),
            structured_events=structured_parse.events,
            message_id=gm_message_id,
        )
        if post_visible_task is not None:
            background_tasks.append(post_visible_task)
    except Exception as _exc:
        diff_summary["npc_post_visible_work"] = {
            **dict(npc_post_visible_work),
            "scheduled": False,
            "error": str(_exc),
        }

    if portrait_task_keys:
        portrait_task = spawn_npc_portrait_task(
            session.id, session.user_id, portrait_task_keys,
            message_id=gm_message_id,
        )
        if portrait_task is not None:
            background_tasks.append(portrait_task)

    if gm_message_id and background_tasks:
        # Spin up a fire-and-forget finaliser that awaits every
        # background task spawned for this turn and emits the
        # `phase3_complete` event so the frontend stops polling.
        from services.trpg_postprocess_steps import PhaseTracker

        tracker = PhaseTracker(gm_message_id)
        for t in background_tasks:
            tracker.add_task(t)
        asyncio.create_task(tracker.wait_and_complete(detail="phase 3 settled"))

    # Per-turn NPC text sync now starts inside post-visible NPC work, after
    # Runtime V2 state/table writeback has produced fresh state versions.

    # Auto-continuation after combat: chatrpg auto-rolls `[CHECK auto=true]`
    # and `[CONTEST]` at marker-resolution time, which means the GM didn't
    # know the outcome when it wrote the marker — its prose stops at the
    # moment of the strike, with the rendered `[dice]` block as the only
    # signal of what happened. Without this hook, the player sees a
    # half-told story and has to send "然后呢" to get aftermath.
    #
    # If the saved GM message contains a rendered `[dice]` block (and we
    # aren't already in a resolve continuation — that path runs once on its
    # own), re-enter `stream_ic_turn` with `intent="resolve"`. The recursive
    # call sees the freshly-saved GM (with the [dice] outcome) in
    # chat_history, runs the framework with `_RESOLVE_USER_HINT`, and
    # writes a second GM bubble narrating the consequences (knife biting
    # in, blood, NPC reaction, world response). One extra LLM call per
    # combat turn — same trade-off as Wave 1 Phase 1.5's pending check
    # resolve continuation.
    needs_continuation = (
        not is_resolve and "[dice]" in (assistant_text or "")
    )
    if needs_continuation:
        yield {
            "type": "thinking",
            "content": "[combat aftermath] auto-continuing GM narration…",
        }
        async for ev in stream_ic_turn(
            db, session, ruleset, "", intent=_RESOLVE_INTENT,
        ):
            yield ev
        return

    yield {
        "type": "done",
        "result": {
            "assistant": assistant_text,
            "diff_summary": diff_summary,
            "thinking_count": len(thinking_lines),
            "marker_count": len(parsed_markers),
            "extension_summary": extension_summary,
            "auto_memory_summary": auto_summary,
            "narrative_compressed": compression.ran,
            "objective": gm_meta.get("objective"),
            "added_notes": gm_meta.get("added_notes") or [],
        },
    }
