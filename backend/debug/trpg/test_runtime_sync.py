"""Runtime sync test — verifies that an in-place edit by the rule
editor agent is picked up by a session's next turn without restart.

Doesn't run the actual game pipeline (slow, requires LLM); instead
exercises the same `_get_ruleset_for_session` read-site every turn
uses, in two separate AsyncSessions, and confirms the second one
returns the post-edit state.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_runtime_sync.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.database import get_session_factory  # noqa: E402
from orm.models import GameSession, Ruleset, User  # noqa: E402
from routes.sessions import _get_ruleset_for_session  # noqa: E402
from services import ruleset_drafts as svc  # noqa: E402


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def assert_eq(label, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}\n  expected: {expected!r}\n  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


# Dedicated test user — keeps smoke-test artefacts separate from the
# developer's real `local` user data.
_SMOKETEST_USER_ID = "local__runtime_sync_smoketest"


async def _ensure_user(factory) -> User:
    async with factory() as db:
        u = await db.execute(select(User).where(User.id == _SMOKETEST_USER_ID))
        existing = u.scalar_one_or_none()
        if existing:
            return existing
        user = User(
            id=_SMOKETEST_USER_ID,
            name=_SMOKETEST_USER_ID,
            username=_SMOKETEST_USER_ID,
            password="",
            role="player",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def main() -> None:
    factory = get_session_factory()
    user = await _ensure_user(factory)

    # 1. Create a base ruleset with a known book_title.
    rs_id = f"rs_test_{uuid.uuid4().hex[:12]}"
    async with factory() as db:
        rs = Ruleset(
            id=rs_id,
            owner_id=user.id,
            is_shared=False,
            book_id="test_book",
            book_title="__runtime_sync_baseline",
            world_mode="test_mode",
            parsed_v6={
                "version": 6,
                "book_id": "test_book",
                "book_title": "__runtime_sync_baseline",
                "world_mode": "test_mode",
                "core_rules": "Initial baseline rules.",
                "companion": {"filename": "world_guide.md", "content": ""},
                "rule_packages": [],
                "parameter_families": [],
                "character_sheet": None,
            },
            dice_ir=None,
            check_spec=None,
            character_ui=None,
            notes="",
        )
        db.add(rs)
        await db.commit()
    print(f"created baseline ruleset {rs_id}")

    # 2. Create a session bound to that ruleset.
    session_id = f"sess_test_{uuid.uuid4().hex[:12]}"
    async with factory() as db:
        sess = GameSession(
            id=session_id,
            user_id=user.id,
            ruleset_id=rs_id,
            title="__runtime_sync_session",
            title_auto=True,
            archived=False,
            setup_state={
                "step": 2,
                "ruleset_id": rs_id,
                "module_id": None,
                "module_title": None,
                "completed": True,
            },
        )
        db.add(sess)
        await db.commit()
    print(f"created session {session_id}")

    # 3. Pretend a "first turn" happens — open a fresh AsyncSession,
    #    resolve the ruleset, capture state.
    async with factory() as db:
        s = await db.get(GameSession, session_id)
        rs_first = await _get_ruleset_for_session(db, s, user)
        first_title = rs_first.book_title
        first_updated = rs_first.updated_at
        first_core = (rs_first.parsed_v6 or {}).get("core_rules", "")
    assert_eq("turn 1 sees baseline title", first_title, "__runtime_sync_baseline")
    assert_eq("turn 1 sees baseline core_rules", first_core, "Initial baseline rules.")

    # 4. Create an in-place edit draft bound to the same ruleset, apply
    #    a patch via the same code path the rule editor agent uses.
    async with factory() as db:
        draft = await svc.create_draft(
            db, owner_id=user.id, target_ruleset_id=rs_id,
        )
        draft_id = draft.id
    async with factory() as db:
        await svc.apply_ops_to_draft(
            db, draft_id=draft_id, owner_id=user.id,
            raw_ops=[
                {"op": "set_meta", "field": "book_title",
                 "value": "__runtime_sync_AFTER_EDIT"},
                {"op": "set_core_rules",
                 "content": "Edited: stealth uses 1d100 vs skill."},
            ],
        )
    print(f"applied in-place edit via draft {draft_id}")

    # 5. Pretend the "next turn" happens — DIFFERENT fresh AsyncSession
    #    (mimicking the per-request session in `_stream_with_fresh_db`).
    #    This is the moment-of-truth: does the next turn see the edit?
    async with factory() as db:
        s = await db.get(GameSession, session_id)
        rs_second = await _get_ruleset_for_session(db, s, user)
        second_title = rs_second.book_title
        second_updated = rs_second.updated_at
        second_core = (rs_second.parsed_v6 or {}).get("core_rules", "")

    assert_eq(
        "turn 2 sees edited title",
        second_title, "__runtime_sync_AFTER_EDIT",
    )
    assert_eq(
        "turn 2 sees edited core_rules",
        second_core, "Edited: stealth uses 1d100 vs skill.",
    )
    assert_true(
        "ruleset.updated_at advanced",
        second_updated > first_updated,
        why=f"first={first_updated} second={second_updated}",
    )

    # 6. Verify dice agent path also flows through. We'll skip the full
    #    LLM compile here and just fake-write a dice_ir column update,
    #    then re-fetch.
    async with factory() as db:
        rs_to_edit = await db.get(Ruleset, rs_id)
        rs_to_edit.dice_ir = {
            "schema_version": "ruleset_dice_ir_compiler_artifact_v1",
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "model": "test",
            "package": {
                "compiled": {
                    "schema_version": "v1",
                    "check_specs": [{
                        "procedure_id": "fake_test",
                        "name": "fake",
                        "check_spec": {"engine": "coc_7e_d100"},
                        "validation": {"ok": True},
                    }],
                    "default_procedure_id": "fake_test",
                    "overall_ok": True,
                },
            },
        }
        rs_to_edit.updated_at = datetime.now(timezone.utc)
        await db.commit()

    async with factory() as db:
        s = await db.get(GameSession, session_id)
        rs_third = await _get_ruleset_for_session(db, s, user)
        compiled = (
            ((rs_third.dice_ir or {}).get("package") or {}).get("compiled")
            or {}
        )
        specs = compiled.get("check_specs") or []
    assert_true(
        "turn 3 sees the new dice_ir column",
        len(specs) >= 1 and specs[0].get("procedure_id") == "fake_test",
    )

    # 7. Cleanup. Delete session first (it has FK on rulesets), then
    #    draft (FK cascades messages/edits), then the ruleset itself.
    async with factory() as db:
        await svc.delete_draft(db, draft_id=draft_id, owner_id=user.id)
    async with factory() as db:
        s_del = await db.get(GameSession, session_id)
        if s_del:
            await db.delete(s_del)
        await db.commit()
    async with factory() as db:
        rs_del = await db.get(Ruleset, rs_id)
        if rs_del:
            await db.delete(rs_del)
        await db.commit()
    print(f"cleaned up draft / ruleset / session")
    print("\nAll runtime sync assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
