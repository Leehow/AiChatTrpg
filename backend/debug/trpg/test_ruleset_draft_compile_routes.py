"""Focused service smoke for the P0.5 / P0.8 design-state compile path.

Lives in its own file so that `test_ruleset_drafts_routes.py` stays
under the 400-line cap. Hits the service layer directly (no HTTP) to
prove four claims:

1. Fresh blank draft (empty / `{}` design_state) -> service normalizes
   to canonical `empty_design_state()` and returns a structured
   `CompileBlockedResult` (the route maps this to HTTP 200 with
   `status="blocked"`); parsed_v6 unchanged; validation_report has
   `can_compile=False` with the expected ready blockers; the persisted
   design_state shows `schema_version == 1` and
   `compile.status == "failed"`.
2. Partial design_state with blocking validator issues ->
   `CompileBlockedResult`; parsed_v6 unchanged; validation_report and
   `design_state.compile.status="failed"` persisted.
3. Fully valid design_state -> `CompileSuccessResult`; parsed_v6 is
   replaced; stale flags set; `RulesetDraftEdit` audit row written
   with the namespaced op `compile_design_state`.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_ruleset_draft_compile_routes.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from agents.rule_editor.design_state import (  # noqa: E402
    apply_design_ops,
    empty_design_state,
    parse_design_ops,
)
from core.config import get_settings  # noqa: E402
from core.database import get_engine, get_session_factory  # noqa: E402
from main import _FORWARD_COLUMN_MIGRATIONS  # noqa: E402
from orm.models import (  # noqa: E402
    Base, RulesetDraft, RulesetDraftEdit, User,
)
from services import ruleset_drafts as svc  # noqa: E402
from services.ruleset_draft_compile import (  # noqa: E402
    CompileBlockedResult,
    CompileSuccessResult,
    compile_design_for_draft,
)


_TEST_DRAFT_TITLE = "__test_drafts_compile_sentinel"


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


async def _cleanup(factory, owner_id: str) -> None:
    async with factory() as db:
        rows = await db.execute(
            select(RulesetDraft).where(
                RulesetDraft.owner_id == owner_id,
                RulesetDraft.title.like("__test_drafts_compile_%"),
            )
        )
        for d in rows.scalars().all():
            await db.delete(d)
        await db.commit()


def _partial_design_state() -> dict:
    return apply_design_ops(empty_design_state(), parse_design_ops([
        {"op": "set_brief_field", "field": "concept",
         "value": "Half-baked pitch."},
    ])).design_state


def _full_design_state(seed: dict) -> dict:
    return apply_design_ops(seed, parse_design_ops([
        {"op": "set_blueprint", "blueprint_id": "d20_heroic_adventure",
         "slots_required": []},
        {"op": "set_taxonomy_field", "field": "setting_type",
         "value": "adventure"},
        {"op": "set_core_loop", "summary": "Frame; act; resolve."},
        {"op": "set_resolution_model",
         "mechanic": "d20 vs DC", "dice": "1d20+mod"},
        {"op": "set_character_model",
         "attributes": [{"id": "str", "name": "Strength"}]},
        {"op": "upsert_procedure", "id": "combat",
         "procedure": {"name": "Combat", "summary": "Fight."}},
        {"op": "upsert_catalog_entry", "catalog": "skills", "id": "athletics",
         "entry": {"id": "athletics", "name": "Athletics"}},
    ])).design_state


async def _seed_design_state(factory, draft_id: str, design_state: dict) -> None:
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        d.design_state = design_state
        flag_modified(d, "design_state")
        await db.commit()


async def main() -> None:
    await _apply_forward_migrations()
    factory = get_session_factory()
    owner_id = await _ensure_user(factory)
    await _cleanup(factory, owner_id)

    # 1. Fresh blank draft (empty design_state) -> structured blocked
    # result, not HTTPException. The route maps CompileBlockedResult to
    # HTTP 200 with status="blocked" (see routes/ruleset_draft_compile.py).
    async with factory() as db:
        draft = await svc.create_draft(
            db, owner_id=owner_id, title=_TEST_DRAFT_TITLE,
        )
        draft_id = draft.id
        parsed_v6_initial = dict(draft.parsed_v6 or {})
        # `create_draft` initialises design_state to {} -- assert that so
        # the regression covers the literal "fresh blank" shape from the
        # P0.7 frontend flow (Compile clicked on a brand-new draft).
        assert_eq(
            "fresh-blank: design_state starts as {}",
            dict(draft.design_state or {}), {},
        )

    async with factory() as db:
        result = await compile_design_for_draft(
            db, draft_id=draft_id, owner_id=owner_id,
        )
        assert_true(
            "fresh-blank: result is CompileBlockedResult",
            isinstance(result, CompileBlockedResult),
        )
        # Route layer maps this to HTTP 200 / status="blocked".
        assert_eq(
            "fresh-blank: validation_report.can_compile is False",
            result.validation_report.get("can_compile"), False,
        )
        ready = set(result.ready_blockers)
        for code in (
            "blueprint_required",
            "core_loop_summary_missing",
            "resolution_mechanic_missing",
        ):
            assert_true(
                f"fresh-blank: ready_blockers contains {code}",
                code in ready,
            )

    # Follow-up GET: persisted design_state is now canonical empty (not
    # `{}`), with schema_version=1, phase="intake", and the compile
    # block stamped failed. parsed_v6 is preserved.
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        ds = d.design_state or {}
        assert_eq(
            "fresh-blank: design_state.schema_version == 1",
            ds.get("schema_version"), 1,
        )
        assert_eq(
            "fresh-blank: design_state.phase == intake",
            ds.get("phase"), "intake",
        )
        assert_eq(
            "fresh-blank: compile.status == failed",
            (ds.get("compile") or {}).get("status"), "failed",
        )
        assert_true(
            "fresh-blank: validation_report persisted",
            bool(d.validation_report),
        )
        assert_eq(
            "fresh-blank: persisted validation_report.can_compile False",
            (d.validation_report or {}).get("can_compile"), False,
        )
        assert_eq(
            "fresh-blank: parsed_v6 unchanged",
            dict(d.parsed_v6 or {}), parsed_v6_initial,
        )

    # 2. Partial design_state -> validator blocks; parsed_v6 untouched.
    await _seed_design_state(factory, draft_id, _partial_design_state())
    async with factory() as db:
        result = await compile_design_for_draft(
            db, draft_id=draft_id, owner_id=owner_id,
        )
        assert_true(
            "blocked: result type", isinstance(result, CompileBlockedResult),
        )
        assert_true(
            "blocked: ready_blockers populated",
            bool(result.ready_blockers),
        )
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq(
            "blocked: parsed_v6 untouched",
            dict(d.parsed_v6 or {}), parsed_v6_initial,
        )
        assert_true(
            "blocked: validation_report persisted",
            bool(d.validation_report),
        )
        assert_eq(
            "blocked: compile.status=failed",
            (d.design_state or {}).get("compile", {}).get("status"),
            "failed",
        )

    # 3. Full design_state -> success path.
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        full = _full_design_state(d.design_state or empty_design_state())
    await _seed_design_state(factory, draft_id, full)
    async with factory() as db:
        result = await compile_design_for_draft(
            db, draft_id=draft_id, owner_id=owner_id,
        )
        assert_true(
            "success: result type", isinstance(result, CompileSuccessResult),
        )
        assert_true(
            "success: edit_id set", isinstance(result.edit_id, str) and result.edit_id,
        )
        assert_true(
            "success: core_rules emitted",
            "core_rules" in result.sections_emitted,
        )
        assert_true(
            "success: character_sheet emitted",
            "character_sheet" in result.sections_emitted,
        )
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        parsed_v6 = d.parsed_v6 or {}
        assert_eq(
            "success: book_title inferred",
            parsed_v6.get("book_title"), "Half-baked pitch.",
        )
        assert_eq(
            "success: world_mode from taxonomy",
            parsed_v6.get("world_mode"), "adventure",
        )
        assert_eq(
            "success: 1 rule_package",
            len(parsed_v6.get("rule_packages") or []), 1,
        )
        assert_true(
            "success: needs_dice_compile flagged",
            bool(d.needs_dice_compile),
        )
        assert_true(
            "success: needs_character_ui_compile flagged",
            bool(d.needs_character_ui_compile),
        )
        assert_eq(
            "success: compile.status=success",
            (d.design_state or {}).get("compile", {}).get("status"),
            "success",
        )
        edits = await db.execute(
            select(RulesetDraftEdit).where(
                RulesetDraftEdit.draft_id == draft_id,
            )
        )
        edit_rows = list(edits.scalars().all())
        assert_true(
            "success: compile_design_state audit row written",
            any(
                isinstance(e.ops, list)
                and e.ops
                and isinstance(e.ops[0], dict)
                and e.ops[0].get("op") == "compile_design_state"
                for e in edit_rows
            ),
        )

    await _cleanup(factory, owner_id)
    print("\nAll compile-design route smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
