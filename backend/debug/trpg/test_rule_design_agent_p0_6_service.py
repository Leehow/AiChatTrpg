"""DB-backed service smokes for the P0.6 main rule-editor agent integration.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_agent_p0_6_service.py

Covers:

1. `apply_design_ops_to_draft` persists design_state, validation_report,
   design_phase, writes a namespaced `apply_design_ops` edit row, and
   leaves parsed_v6 untouched.
2. `apply_blueprint_to_draft` seeds defaults into design_state, persists
   the validation report, writes an `apply_blueprint` audit row, and
   leaves parsed_v6 untouched.
3. The `read_design_state` tool (exercised through its FunctionTool
   wrapper) returns summary + report from a real draft, with no
   `_design_state_changed` marker.

Pure schema / prompt / event-helper smokes live in
`test_rule_design_agent_p0_6_schema.py`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select, text  # noqa: E402

from agents.rule_editor.tools.base import ToolContext  # noqa: E402
from agents.rule_editor.tools.design_state import (  # noqa: E402
    read_design_state_tool,
)
from core.config import get_settings  # noqa: E402
from core.database import get_engine, get_session_factory  # noqa: E402
from main import _FORWARD_COLUMN_MIGRATIONS  # noqa: E402
from orm.models import (  # noqa: E402
    Base, RulesetDraft, RulesetDraftEdit, User,
)
from services import ruleset_drafts as svc  # noqa: E402
from services.ruleset_draft_design import (  # noqa: E402
    apply_blueprint_to_draft,
    apply_design_ops_to_draft,
)


_TEST_DRAFT_TITLE = "__test_drafts_p06_sentinel"


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
                RulesetDraft.title.like("__test_drafts_p06_%"),
            )
        )
        for d in rows.scalars().all():
            await db.delete(d)
        await db.commit()


async def _ops_smoke(factory, owner_id: str) -> str:
    print("\n--- 1. apply_design_ops_to_draft ---")
    async with factory() as db:
        draft = await svc.create_draft(
            db, owner_id=owner_id, title=_TEST_DRAFT_TITLE,
        )
        draft_id = draft.id
        parsed_v6_initial = dict(draft.parsed_v6 or {})

    async with factory() as db:
        result = await apply_design_ops_to_draft(
            db,
            draft_id=draft_id,
            owner_id=owner_id,
            raw_ops=[
                {"op": "set_phase", "phase": "blueprint_selection"},
                {
                    "op": "set_brief_field", "field": "concept",
                    "value": "Solo paranormal investigation in a small town.",
                },
                {"op": "add_assumption", "assumption": "Single PC only."},
                {"op": "set_taxonomy_field", "field": "tone",
                 "value": "tense"},
            ],
            message_id=None,
        )
    assert_true(
        "design ops: edit_id returned",
        bool(result.edit_id),
    )
    assert_true(
        "design ops: diff non-empty",
        bool(result.diff),
    )
    assert_eq(
        "design ops: phase persisted",
        result.design_phase, "blueprint_selection",
    )
    assert_true(
        "design ops: validation_report present",
        bool(result.validation_report),
    )

    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq(
            "design ops: parsed_v6 untouched",
            dict(d.parsed_v6 or {}), parsed_v6_initial,
        )
        assert_eq(
            "design ops: design_phase persisted",
            d.design_phase, "blueprint_selection",
        )
        assert_eq(
            "design ops: brief.concept persisted",
            (d.design_state or {}).get("brief", {}).get("concept"),
            "Solo paranormal investigation in a small town.",
        )
        assert_true(
            "design ops: validation_report persisted",
            bool(d.validation_report),
        )
        edits = await db.execute(
            select(RulesetDraftEdit).where(
                RulesetDraftEdit.draft_id == draft_id,
            )
        )
        edit_rows = list(edits.scalars().all())
        assert_true(
            "design ops: apply_design_ops audit row written",
            any(
                isinstance(e.ops, list) and e.ops
                and isinstance(e.ops[0], dict)
                and e.ops[0].get("op") == "apply_design_ops"
                for e in edit_rows
            ),
        )
    return draft_id


async def _blueprint_smoke(
    factory, owner_id: str, draft_id: str,
) -> dict:
    print("\n--- 2. apply_blueprint_to_draft ---")
    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        parsed_v6_initial = dict(d.parsed_v6 or {})

    async with factory() as db:
        bp_result = await apply_blueprint_to_draft(
            db,
            draft_id=draft_id,
            owner_id=owner_id,
            blueprint_id="d20_heroic_adventure",
            message_id=None,
        )
    assert_eq(
        "blueprint: id recorded on result",
        bp_result.blueprint_id, "d20_heroic_adventure",
    )
    assert_true(
        "blueprint: sections_seeded non-empty",
        bool(bp_result.sections_seeded),
    )
    assert_true(
        "blueprint: validation_report fresh",
        bool(bp_result.validation_report),
    )

    async with factory() as db:
        d = await db.get(RulesetDraft, draft_id)
        assert_eq(
            "blueprint: design_state.blueprint.id persisted",
            (d.design_state or {}).get("blueprint", {}).get("id"),
            "d20_heroic_adventure",
        )
        assert_eq(
            "blueprint: parsed_v6 still untouched",
            dict(d.parsed_v6 or {}), parsed_v6_initial,
        )
        edits = await db.execute(
            select(RulesetDraftEdit).where(
                RulesetDraftEdit.draft_id == draft_id,
            )
        )
        edit_rows = list(edits.scalars().all())
        assert_true(
            "blueprint: apply_blueprint audit row written",
            any(
                isinstance(e.ops, list) and e.ops
                and isinstance(e.ops[0], dict)
                and e.ops[0].get("op") == "apply_blueprint"
                and e.ops[0].get("blueprint_id") == "d20_heroic_adventure"
                for e in edit_rows
            ),
        )
    return parsed_v6_initial


async def _read_tool_smoke(
    factory, owner_id: str, draft_id: str,
) -> None:
    print("\n--- 3. read_design_state tool ---")
    async with factory() as db:
        ctx = ToolContext(
            db=db, owner_id=owner_id, draft_id=draft_id,
            assistant_message_id=None,
        )
        ro = await read_design_state_tool.execute(ctx, {})
    payload = ro.payload
    assert_true(
        "read tool: ok flag",
        payload.get("ok") is True,
    )
    assert_true(
        "read tool: design_summary present",
        isinstance(payload.get("design_summary"), dict)
        and bool(payload["design_summary"]),
    )
    assert_true(
        "read tool: validation_report present",
        isinstance(payload.get("validation_report"), dict)
        and bool(payload["validation_report"]),
    )
    assert_true(
        "read tool: no _design_state_changed marker",
        "_design_state_changed" not in payload,
    )


async def _fresh_draft_read_tool_smoke(factory, owner_id: str) -> None:
    """Regression: a brand-new draft must NOT report `schema_version_unsupported`.

    `RulesetDraft.design_state` defaults to `{}`. Before this fix the
    read tool fed `{}` straight into `validate_design_state`, which
    flagged a schema blocker even though no authoring had happened
    yet. The tool now normalizes via `empty_design_state()`, mirroring
    the service helper.
    """
    print("\n--- 4. read_design_state on fresh draft ---")
    async with factory() as db:
        draft = await svc.create_draft(
            db, owner_id=owner_id, title="__test_drafts_p06_fresh",
        )
        fresh_id = draft.id
        # Sanity: the draft really is starting from `{}` so this test
        # would have caught the bug that motivated the revision.
        assert_eq(
            "fresh draft: design_state empty",
            dict(draft.design_state or {}), {},
        )

    async with factory() as db:
        ctx = ToolContext(
            db=db, owner_id=owner_id, draft_id=fresh_id,
            assistant_message_id=None,
        )
        ro = await read_design_state_tool.execute(ctx, {"include_full": True})
    payload = ro.payload
    report = payload.get("validation_report") or {}
    blocking_codes = [iss.get("code") for iss in (report.get("blocking") or [])]
    assert_true(
        "fresh draft: no schema_version_unsupported blocker",
        "schema_version_unsupported" not in blocking_codes,
        why=f"blocking_codes={blocking_codes!r}",
    )
    ready_blockers = list(report.get("ready_blockers") or [])
    assert_true(
        "fresh draft: no schema_version_unsupported in ready_blockers",
        "schema_version_unsupported" not in ready_blockers,
        why=f"ready_blockers={ready_blockers!r}",
    )
    assert_eq(
        "fresh draft: phase reported as intake",
        payload.get("design_phase"), "intake",
    )
    full_state = payload.get("design_state") or {}
    assert_eq(
        "fresh draft: full state schema_version=1",
        full_state.get("schema_version"), 1,
    )
    assert_eq(
        "fresh draft: full state phase=intake",
        full_state.get("phase"), "intake",
    )


async def main() -> None:
    await _apply_forward_migrations()
    factory = get_session_factory()
    owner_id = await _ensure_user(factory)
    await _cleanup(factory, owner_id)
    try:
        draft_id = await _ops_smoke(factory, owner_id)
        await _blueprint_smoke(factory, owner_id, draft_id)
        await _read_tool_smoke(factory, owner_id, draft_id)
        await _fresh_draft_read_tool_smoke(factory, owner_id)
    finally:
        await _cleanup(factory, owner_id)
    print("\nAll P0.6 service smokes passed.")


if __name__ == "__main__":
    asyncio.run(main())
