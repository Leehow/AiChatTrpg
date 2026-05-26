"""End-to-end smoke test for the ruleset-drafts routes.

Hits the service layer + DB directly (no HTTP) to verify the full CRUD +
apply + undo + promote + in-place cascade flow works against live tables.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_ruleset_drafts_routes.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select, text  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.database import get_engine, get_session_factory  # noqa: E402
from main import _FORWARD_COLUMN_MIGRATIONS  # noqa: E402
from orm.models import (  # noqa: E402
    Base, Ruleset, RulesetDraft, RulesetDraftEdit, RulesetDraftMessage, User,
)
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


async def _apply_forward_migrations() -> None:
    """Mirror the FastAPI lifespan schema bring-up.

    The smoke test bypasses the full ASGI app, so the per-boot
    `Base.metadata.create_all` + `_FORWARD_COLUMN_MIGRATIONS` from
    `backend/main.py` never run. Reuse the SAME migration list (single
    source of truth) so an existing dev DB picks up new columns the
    same way `python run.py` would on its next boot.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _FORWARD_COLUMN_MIGRATIONS:
            await conn.execute(text(stmt))


async def _ensure_user(factory) -> str:
    settings = get_settings()
    async with factory() as db:
        u = await db.execute(select(User).where(User.id == settings.single_user_id))
        existing = u.scalar_one_or_none()
        if existing:
            return existing.id
        user = User(
            id=settings.single_user_id,
            name=settings.single_user_id,
            username=settings.single_user_id,
            password="",
            role="player",
        )
        db.add(user)
        await db.commit()
        return user.id


_TEST_DRAFT_TITLE = "__test_drafts_sentinel"


async def _cleanup(factory, owner_id: str) -> None:
    """Drop ONLY drafts created by this test, identified by the
    sentinel title `__test_drafts_sentinel`. Earlier versions of this
    cleanup deleted ALL drafts owned by `owner_id`, which silently
    nuked the developer's real drafts in single-user mode (owner_id =
    "local"). Audit hooks live on the ROUTE, not the service, so a
    direct `db.delete` here also bypassed forensic logging -- making
    the wipes invisible.
    """
    async with factory() as db:
        # Prefix match catches both the sentinel title and any title
        # the test rewrote via set_meta book_title (which mirrors into
        # draft.title in apply_ops_to_draft).
        rows = await db.execute(
            select(RulesetDraft).where(
                RulesetDraft.owner_id == owner_id,
                RulesetDraft.title.like("__test_drafts_%"),
            )
        )
        for d in rows.scalars().all():
            await db.delete(d)
        # Delete throwaway rulesets created by this test (matches by title prefix).
        rs_rows = await db.execute(
            select(Ruleset).where(
                Ruleset.owner_id == owner_id,
                Ruleset.book_title.like("__test_drafts_%"),
            )
        )
        for r in rs_rows.scalars().all():
            await db.delete(r)
        await db.commit()


async def main() -> None:
    await _apply_forward_migrations()
    factory = get_session_factory()
    owner_id = await _ensure_user(factory)
    await _cleanup(factory, owner_id)

    # 1. Create blank draft.
    async with factory() as db:
        draft = await svc.create_draft(
            db, owner_id=owner_id, title=_TEST_DRAFT_TITLE,
        )
        draft_id = draft.id
        assert_eq("blank: book_title empty", draft.parsed_v6.get("book_title"), "")
        assert_true("blank: title is sentinel", draft.title == _TEST_DRAFT_TITLE)
        assert_true("blank: no target", draft.target_ruleset_id is None)
        # P0.1 design-state-first defaults: empty authoring artifact, `intake`
        # phase, empty validation report.
        assert_eq("blank: design_state default", draft.design_state, {})
        assert_eq("blank: design_phase default", draft.design_phase, "intake")
        assert_eq(
            "blank: validation_report default", draft.validation_report, {},
        )

    # 2. Apply ops.
    async with factory() as db:
        edit = await svc.apply_ops_to_draft(
            db, draft_id=draft_id, owner_id=owner_id,
            raw_ops=[
                {"op": "set_meta", "field": "book_title", "value": "__test_drafts_v1"},
                {"op": "set_meta", "field": "world_mode", "value": "horror"},
                {"op": "upsert_rule_package", "id": "combat",
                 "package": {"content": "# Combat"}},
            ],
        )
        edit_id = edit.id
        assert_eq("apply: 3 diff entries", len(edit.diff), 3)
        assert_true("apply: dice flag set",
                    (await db.get(RulesetDraft, draft_id)).needs_dice_compile)

    # 3. Verify state.
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq("state: book_title", d.parsed_v6["book_title"], "__test_drafts_v1")
        assert_eq("state: 1 rule_package", len(d.parsed_v6["rule_packages"]), 1)

    # 4. Undo the edit.
    async with factory() as db:
        await svc.undo_edit(
            db, draft_id=draft_id, owner_id=owner_id, edit_id=edit_id,
        )
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq("undo: book_title reverted", d.parsed_v6["book_title"], "")
        assert_eq("undo: world_mode reverted", d.parsed_v6["world_mode"], "")
        assert_eq("undo: package removed", len(d.parsed_v6["rule_packages"]), 0)

    # 5. Re-apply for promote test. Promote now requires non-empty
    # core_rules (B1) -- set both fields here.
    async with factory() as db:
        await svc.apply_ops_to_draft(
            db, draft_id=draft_id, owner_id=owner_id,
            raw_ops=[
                {"op": "set_meta", "field": "book_title",
                 "value": "__test_drafts_promoted"},
                {"op": "set_core_rules",
                 "content": "# Test core rules\nMinimal placeholder."},
            ],
        )

    # 5b. Promote with empty core_rules must be refused. Use a sibling
    # draft so the assertion doesn't disturb the main flow.
    async with factory() as db:
        bare = await svc.create_draft(
            db, owner_id=owner_id, title=_TEST_DRAFT_TITLE,
        )
        bare_id = bare.id
        await svc.apply_ops_to_draft(
            db, draft_id=bare_id, owner_id=owner_id,
            raw_ops=[
                {"op": "set_meta", "field": "book_title",
                 "value": "__test_drafts_no_core"},
            ],
        )
    async with factory() as db:
        try:
            await svc.promote_draft(
                db, draft_id=bare_id, owner_id=owner_id, mode="new",
            )
        except Exception as e:
            assert_true(
                "B1: promote refused when core_rules empty",
                "core_rules" in str(e),
            )
        else:
            fail("B1", "expected promote to refuse empty core_rules")

    # 6. Promote to new ruleset.
    async with factory() as db:
        new_rs_id = await svc.promote_draft(
            db, draft_id=draft_id, owner_id=owner_id, mode="new",
        )
    async with factory() as db:
        rs = await db.get(Ruleset, new_rs_id)
        assert_eq("promote new: book_title",
                  rs.book_title, "__test_drafts_promoted")
        assert_eq("promote new: parsed_v6 mirrored",
                  rs.parsed_v6.get("book_title"), "__test_drafts_promoted")
        # Draft retained.
        d = await db.get(RulesetDraft, draft_id)
        assert_true("promote: draft retained", d is not None)

    # 7. In-place cascade: create another draft bound to the new ruleset.
    async with factory() as db:
        cascade_draft = await svc.create_draft(
            db, owner_id=owner_id, target_ruleset_id=new_rs_id,
            title=_TEST_DRAFT_TITLE,
        )
        cascade_id = cascade_draft.id
        # P0.1: target-mode drafts also start with empty authoring state --
        # design_state is its own artifact, never copied from the target's
        # parsed_v6.
        assert_eq("cascade: design_state empty", cascade_draft.design_state, {})
        assert_eq("cascade: design_phase intake", cascade_draft.design_phase, "intake")
    async with factory() as db:
        await svc.apply_ops_to_draft(
            db, draft_id=cascade_id, owner_id=owner_id,
            raw_ops=[
                {"op": "set_meta", "field": "book_title",
                 "value": "__test_drafts_cascaded"},
            ],
        )
    async with factory() as db:
        rs = await db.get(Ruleset, new_rs_id)
        assert_eq("cascade: source updated",
                  rs.book_title, "__test_drafts_cascaded")
        assert_eq("cascade: source parsed_v6 updated",
                  rs.parsed_v6.get("book_title"), "__test_drafts_cascaded")

    # 8. Append message.
    async with factory() as db:
        m1 = await svc.append_message(
            db, draft_id=draft_id, owner_id=owner_id,
            role="user", content={"text": "hello"},
        )
        m2 = await svc.append_message(
            db, draft_id=draft_id, owner_id=owner_id,
            role="assistant", content={"text": "hi"},
        )
        assert_eq("messages: seq increments", (m1.seq, m2.seq), (1, 2))

    # 9. List drafts (should include both).
    async with factory() as db:
        drafts = await svc.list_drafts(db, owner_id=owner_id)
        assert_true("list: at least 2 drafts", len(drafts) >= 2)

    # 9b. Route serializers expose the P0.1 design-state fields with a
    # stable shape -- DraftSummary carries `design_phase`, DraftDetail
    # adds `design_state` and `validation_report` on top of `parsed_v6`.
    async with factory() as db:
        from routes.ruleset_drafts import _detail, _summary  # noqa: WPS433
        d = await db.get(RulesetDraft, draft_id)
        summary = _summary(d)
        assert_eq("summary: design_phase", summary.design_phase, "intake")
        assert_true(
            "summary: legacy fields preserved",
            hasattr(summary, "needs_dice_compile")
            and hasattr(summary, "needs_character_ui_compile")
            and hasattr(summary, "target_ruleset_id"),
        )
        detail = await _detail(db, d, owner_id)
        assert_eq("detail: design_state default", detail.design_state, {})
        assert_eq(
            "detail: validation_report default", detail.validation_report, {},
        )
        assert_true(
            "detail: parsed_v6 preserved", isinstance(detail.parsed_v6, dict),
        )

    # 10. Auth: another user cannot read.
    async with factory() as db:
        try:
            await svc.get_draft(db, draft_id=draft_id, owner_id="someone-else")
        except Exception as e:
            assert_true("auth: 404 for other user", "404" in str(e) or "Draft not found" in str(e))
        else:
            fail("auth", "expected HTTPException")

    # 11. Bad-op rollback.
    async with factory() as db:
        try:
            await svc.apply_ops_to_draft(
                db, draft_id=draft_id, owner_id=owner_id,
                raw_ops=[
                    {"op": "set_meta", "field": "book_title",
                     "value": "should_not_persist"},
                    {"op": "remove_rule_package", "id": "doesnotexist"},
                ],
            )
        except Exception:
            pass
        else:
            fail("bad-op rollback", "expected PatchError")
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq("rollback: book_title preserved",
                  d.parsed_v6["book_title"], "__test_drafts_promoted")

    # 12. Delete draft cascades messages + edits.
    async with factory() as db:
        await svc.delete_draft(db, draft_id=draft_id, owner_id=owner_id)
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_true("delete: gone", d is None)
        msgs = await db.execute(
            select(RulesetDraftMessage).where(
                RulesetDraftMessage.draft_id == draft_id,
            )
        )
        assert_eq("delete: messages cascade",
                  len(list(msgs.scalars().all())), 0)
        edits = await db.execute(
            select(RulesetDraftEdit).where(
                RulesetDraftEdit.draft_id == draft_id,
            )
        )
        assert_eq("delete: edits cascade",
                  len(list(edits.scalars().all())), 0)

    await _cleanup(factory, owner_id)
    print("\nAll route smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
