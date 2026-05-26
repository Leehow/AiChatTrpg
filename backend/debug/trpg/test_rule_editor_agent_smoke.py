"""End-to-end smoke test for the rule editor agent loop.

Talks to the actual default LLM (codex-relay / gpt-5.5 by default), so
this test makes a real network call. Skip if the model pool isn't
configured.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_editor_agent_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.agent import AgentConfig, run_agent_turn  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.database import get_session_factory  # noqa: E402
from orm.models import User  # noqa: E402
from services import model_pool, ruleset_drafts as svc  # noqa: E402
from sqlalchemy import select  # noqa: E402


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


# Dedicated test user — keeps smoke-test drafts completely separate
# from the developer's real `local` user data. Even if the test wipes
# everything it owns, the developer's drafts are untouched.
_SMOKETEST_USER_ID = "local__rule_editor_smoketest"


async def _ensure_user(factory) -> str:
    async with factory() as db:
        u = await db.execute(select(User).where(User.id == _SMOKETEST_USER_ID))
        existing = u.scalar_one_or_none()
        if existing:
            return existing.id
        user = User(
            id=_SMOKETEST_USER_ID,
            name=_SMOKETEST_USER_ID,
            username=_SMOKETEST_USER_ID,
            password="",
            role="player",
        )
        db.add(user)
        await db.commit()
        return user.id


async def main() -> None:
    factory = get_session_factory()
    owner_id = await _ensure_user(factory)

    # Resolve the active LLM config.
    async with factory() as db:
        entry = await model_pool.get_default(db)
        if entry is None:
            print("SKIP: no default model in pool — cannot run smoke test")
            return
        from routes.rulesets import _resolve_default_compiler_config
        cfg = await _resolve_default_compiler_config(db)

    if not cfg.get("api_key") or not cfg.get("base_url"):
        print(f"SKIP: no api_key/base_url for `{entry.provider}`")
        return

    config = AgentConfig(
        provider=entry.provider,
        model=str(cfg.get("model") or ""),
        base_url=str(cfg.get("base_url") or ""),
        api_key=str(cfg.get("api_key") or ""),
    )
    print(f"using provider={config.provider} model={config.model}")

    # Create a fresh blank draft.
    async with factory() as db:
        draft = await svc.create_draft(db, owner_id=owner_id)
        draft_id = draft.id
    print(f"created draft {draft_id}")

    user_text = (
        "请为我列出 ChatRPG 中 12 种规则包范式（rule package paradigms）"
        "的名字和一句话解释。不要修改任何东西，只是讨论。"
    )

    print("\n=== streaming agent turn ===\n")
    seen_event_types: list[str] = []
    text_total = ""
    tool_calls: list[str] = []

    async with factory() as db:
        async for ev in run_agent_turn(
            db=db,
            owner_id=owner_id,
            draft_id=draft_id,
            user_text=user_text,
            config=config,
        ):
            t = ev.get("type", "")
            seen_event_types.append(t)
            if t == "text_delta":
                d = ev.get("delta", "")
                text_total += d
                print(d, end="", flush=True)
            elif t == "tool_call_started":
                tool_calls.append(str(ev.get("tool_name") or ""))
                print(f"\n[tool call] {ev.get('tool_name')}", flush=True)
            elif t == "tool_result":
                err = ev.get("result", {}).get("error")
                tag = "error" if err else "ok"
                print(f"\n[tool result {tag}] {ev.get('tool_name')}", flush=True)
            elif t == "turn_done":
                print(
                    f"\n\n[turn_done] stop_reason={ev.get('stop_reason')} "
                    f"error={ev.get('error', '')}",
                    flush=True,
                )

    print("\n=== assertions ===")
    assert_true("got user_message_saved", "user_message_saved" in seen_event_types)
    assert_true("got message_started", "message_started" in seen_event_types)
    assert_true(
        "got at least one text_delta",
        seen_event_types.count("text_delta") > 0,
    )
    assert_true("got message_completed", "message_completed" in seen_event_types)
    assert_true("got turn_done", "turn_done" in seen_event_types)
    assert_true(
        "no critical error",
        not any(
            ev_type == "turn_done"
            for ev_type in seen_event_types
            if "error" in str(ev_type)
        ),
    )
    assert_true("text contains substantive output", len(text_total) > 30)

    # Cleanup.
    async with factory() as db:
        await svc.delete_draft(db, draft_id=draft_id, owner_id=owner_id)
    print(f"cleaned up draft {draft_id}")
    print("\nAll smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
