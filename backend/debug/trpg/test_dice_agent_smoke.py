"""End-to-end smoke test for the dice agent.

Asks the agent to design a CoC-style stealth check from plain
language, then verifies the compiled procedure landed in
`draft.parsed_v6.dice_ir`. Real LLM call (~30-60s).

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_dice_agent_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor_dice.agent import (  # noqa: E402
    DiceAgentConfig,
    run_dice_agent_turn,
)
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
# from the developer's real `local` user data.
_SMOKETEST_USER_ID = "local__dice_agent_smoketest"


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

    async with factory() as db:
        entry = await model_pool.get_default(db)
        if entry is None:
            print("SKIP: no default model in pool")
            return
        from routes.rulesets import _resolve_default_compiler_config
        cfg = await _resolve_default_compiler_config(db)

    if not cfg.get("api_key") or not cfg.get("base_url"):
        print(f"SKIP: no api_key/base_url for `{entry.provider}`")
        return

    config = DiceAgentConfig(
        provider=entry.provider,
        model=str(cfg.get("model") or ""),
        base_url=str(cfg.get("base_url") or ""),
        api_key=str(cfg.get("api_key") or ""),
    )
    print(f"using provider={config.provider} model={config.model}")

    async with factory() as db:
        draft = await svc.create_draft(db, owner_id=owner_id)
        draft_id = draft.id
    print(f"created draft {draft_id}")

    user_text = (
        "Design a CoC-style stealth check: roll 1d100 under the "
        "Stealth skill (typical value 50). Roll <= skill/5 is an "
        "extreme success, <= skill/2 is hard success, <= skill is "
        "regular success, > skill is failure, 96+ is fumble. Use "
        "engine_hint coc_7e_d100. Procedure id: stealth_check."
    )

    seen: list[str] = []
    text_total = ""
    tool_calls: list[str] = []
    saw_dice_state_changed = False
    error_seen: str | None = None

    print("\n=== streaming dice agent turn ===\n")
    async with factory() as db:
        async for ev in run_dice_agent_turn(
            db=db,
            owner_id=owner_id,
            draft_id=draft_id,
            user_text=user_text,
            history=None,
            config=config,
        ):
            t = ev.get("type", "")
            seen.append(t)
            if t == "text_delta":
                d = ev.get("delta", "")
                text_total += d
                print(d, end="", flush=True)
            elif t == "tool_call_started":
                tool_calls.append(str(ev.get("tool_name") or ""))
                print(f"\n[tool] {ev.get('tool_name')}", flush=True)
            elif t == "tool_result":
                err = ev.get("result", {}).get("error")
                tag = "error" if err else "ok"
                print(f"\n[tool result {tag}] {ev.get('tool_name')}", flush=True)
                if err:
                    print(f"   error: {ev['result'].get('message', '')}", flush=True)
            elif t == "dice_state_changed":
                saw_dice_state_changed = True
                print("\n[dice_state_changed]", flush=True)
            elif t == "turn_done":
                stop = ev.get("stop_reason")
                err_str = ev.get("error", "")
                print(f"\n\n[turn_done] stop_reason={stop} error={err_str}", flush=True)
                if stop == "error":
                    error_seen = err_str

    print("\n=== assertions ===")
    assert_true("no top-level error", error_seen is None, why=error_seen or "")
    assert_true(
        "called design_dice_procedure",
        "design_dice_procedure" in tool_calls,
    )
    assert_true(
        "got dice_state_changed event",
        saw_dice_state_changed,
        why="design_dice_procedure was expected to succeed and persist",
    )

    # Verify the draft now has a compiled procedure.
    async with factory() as db:
        d = await svc.get_draft(db, draft_id=draft_id, owner_id=owner_id)
        compiled = (
            ((d.parsed_v6 or {}).get("dice_ir") or {}).get("package", {})
            .get("compiled", {})
        )
        specs = compiled.get("check_specs") or []
        assert_true(
            "draft.parsed_v6.dice_ir has at least one compiled spec",
            len(specs) >= 1,
        )
        if specs:
            first = specs[0]
            print(f"\nfirst spec: id={first.get('procedure_id')} "
                  f"engine={(first.get('check_spec') or {}).get('engine')} "
                  f"validation_ok={(first.get('validation') or {}).get('ok')}")

    # Cleanup.
    async with factory() as db:
        await svc.delete_draft(db, draft_id=draft_id, owner_id=owner_id)
    print(f"\ncleaned up draft {draft_id}")
    print("\nAll dice agent smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
