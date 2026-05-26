"""Service layer for the conversational rule editor draft.

CRUD on drafts + the apply / undo / promote pipelines. The agent loop in
P3 calls into `apply_ops_to_draft` from inside its tool handler. Per-turn
runtime sync (P4) reads `Ruleset.updated_at` cascaded by these helpers.

See: docs/design/2026-05-01-rule-editor-agent.md
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from agents.rule_editor.patch_ops import (
    PatchError,
    apply_ops as apply_ops_pure,
    parse_ops,
)
from agents.rule_editor.template import empty_v6
from orm.models import (
    Ruleset,
    RulesetDraft,
    RulesetDraftEdit,
    RulesetDraftMessage,
)
from services.ruleset_draft_undo import undo_edit as _undo_edit_impl


logger = logging.getLogger("chatrpg.ruleset_drafts")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_draft(
    db: AsyncSession, draft_id: str, owner_id: str,
) -> RulesetDraft:
    draft = await db.get(RulesetDraft, draft_id)
    if draft is None or draft.owner_id != owner_id:
        raise HTTPException(404, "Draft not found")
    return draft


async def _load_owned_ruleset(
    db: AsyncSession, ruleset_id: str, owner_id: str,
) -> Ruleset:
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None:
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != owner_id:
        raise HTTPException(403, "only the owner can edit this ruleset")
    return rs


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_draft(
    db: AsyncSession,
    *,
    owner_id: str,
    base_ruleset_id: str | None = None,
    target_ruleset_id: str | None = None,
    title: str | None = None,
) -> RulesetDraft:
    """Create a draft. Three modes:

    1. blank: both ids None -> fresh empty V6 template.
    2. fork: base_ruleset_id set -> copy parsed_v6 from that ruleset.
    3. in-place: target_ruleset_id set -> copy parsed_v6 from target,
       bind for cascading apply_patch writes. Caller must own the target.
    """
    parsed_v6: dict[str, Any]
    inferred_title = title

    if target_ruleset_id:
        target = await _load_owned_ruleset(db, target_ruleset_id, owner_id)
        parsed_v6 = copy.deepcopy(target.parsed_v6 or empty_v6())
        if not inferred_title:
            inferred_title = target.book_title or str(parsed_v6.get("book_title") or "")
    elif base_ruleset_id:
        base = await db.get(Ruleset, base_ruleset_id)
        if base is None or (base.owner_id != owner_id and not base.is_shared):
            raise HTTPException(404, "Base ruleset not found")
        parsed_v6 = copy.deepcopy(base.parsed_v6 or empty_v6())
        if not inferred_title:
            inferred_title = (
                f"{base.book_title} (Fork)" if base.book_title else "未命名草稿"
            )
    else:
        parsed_v6 = empty_v6()
        if not inferred_title:
            inferred_title = "未命名草稿"

    draft = RulesetDraft(
        id=_new_id("draft"),
        owner_id=owner_id,
        title=inferred_title or "未命名草稿",
        parsed_v6=parsed_v6,
        base_ruleset_id=base_ruleset_id,
        target_ruleset_id=target_ruleset_id,
        needs_dice_compile=False,
        needs_character_ui_compile=False,
        # P0.1: design-state-first authoring artifact starts empty for
        # every mode (blank/fork/in-place). Reducer + validator populate
        # these as the user works; legacy `parsed_v6` is the only thing
        # we copy from base/target.
        design_state={},
        design_phase="intake",
        validation_report={},
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


async def list_drafts(
    db: AsyncSession, *, owner_id: str,
) -> list[RulesetDraft]:
    result = await db.execute(
        select(RulesetDraft)
        .where(RulesetDraft.owner_id == owner_id)
        .order_by(RulesetDraft.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_draft(
    db: AsyncSession, *, draft_id: str, owner_id: str,
) -> RulesetDraft:
    return await _load_draft(db, draft_id, owner_id)


async def list_messages(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    after_seq: int = 0,
    kind: str = "main",
) -> list[RulesetDraftMessage]:
    """Paginated agent transcript reader.

    `kind` filters which transcript to return -- "main" for the rule
    editor pane, "dice" for the dice procedure designer pane. Each
    pane reads only its own kind so the two stay independent.
    """
    await _load_draft(db, draft_id, owner_id)
    result = await db.execute(
        select(RulesetDraftMessage)
        .where(
            RulesetDraftMessage.draft_id == draft_id,
            RulesetDraftMessage.kind == kind,
            RulesetDraftMessage.seq > after_seq,
        )
        .order_by(RulesetDraftMessage.seq.asc())
    )
    return list(result.scalars().all())


async def list_edits(
    db: AsyncSession, *, draft_id: str, owner_id: str,
) -> list[RulesetDraftEdit]:
    await _load_draft(db, draft_id, owner_id)
    result = await db.execute(
        select(RulesetDraftEdit)
        .where(RulesetDraftEdit.draft_id == draft_id)
        .order_by(RulesetDraftEdit.created_at.desc())
        .limit(200)
    )
    return list(result.scalars().all())


async def delete_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    audit_actor: str | None = None,
    audit_source: str = "service",
) -> None:
    """Delete a draft + emit a forensic audit log line.

    The audit hook lives HERE rather than only on the route so that any
    code path which deletes a draft (route, service caller, smoke test
    cleanup) leaves a trace. This is what makes "where did my draft go?"
    answerable. Caller may pass `audit_actor` if it's not the owner
    (e.g. an automated cleanup), and `audit_source` to tag the path.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    pre_title = draft.title
    pre_target = draft.target_ruleset_id
    await db.delete(draft)
    await db.commit()
    try:
        from core.audit_log import audit
        audit(
            "draft.delete",
            actor=audit_actor or owner_id,
            target=draft_id,
            extra={
                "title": pre_title,
                "target_ruleset_id": pre_target,
                "source": audit_source,
            },
        )
    except Exception:
        # Audit must never raise into a delete path.
        pass


# ---------------------------------------------------------------------------
# Apply / undo
# ---------------------------------------------------------------------------


async def apply_ops_to_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    raw_ops: list[dict[str, Any]],
    message_id: str | None = None,
) -> RulesetDraftEdit:
    """Apply a batch of patch ops; cascade to target ruleset if any.

    Raises PatchError (caller must translate to HTTP) on bad ops.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    ops = parse_ops(raw_ops)
    result = apply_ops_pure(draft.parsed_v6 or empty_v6(), ops)

    draft.parsed_v6 = result.parsed_v6
    flag_modified(draft, "parsed_v6")
    if result.needs_dice_compile:
        draft.needs_dice_compile = True
    if result.needs_character_ui_compile:
        draft.needs_character_ui_compile = True

    # Keep the draft's display title in sync with meta.book_title so the
    # toolbar / sidebar reflect bootstrap_framework / set_meta edits.
    new_title = str(result.parsed_v6.get("book_title") or "").strip()
    if new_title and new_title != draft.title:
        draft.title = new_title

    if draft.target_ruleset_id:
        target = await db.get(Ruleset, draft.target_ruleset_id)
        if target is not None and target.owner_id == owner_id:
            target.parsed_v6 = copy.deepcopy(result.parsed_v6)
            flag_modified(target, "parsed_v6")
            target.book_title = str(result.parsed_v6.get("book_title") or "")
            target.world_mode = str(result.parsed_v6.get("world_mode") or "")
            target.book_id = str(result.parsed_v6.get("book_id") or "")
            target.updated_at = _now()

    edit = RulesetDraftEdit(
        id=_new_id("edit"),
        draft_id=draft.id,
        message_id=message_id,
        ops=[op.model_dump() for op in ops],
        diff=[d.model_dump() for d in result.diff],
        undone=False,
    )
    db.add(edit)
    await db.commit()
    await db.refresh(edit)
    await db.refresh(draft)
    return edit


async def undo_edit(
    db: AsyncSession, *, draft_id: str, owner_id: str, edit_id: str,
) -> RulesetDraftEdit:
    draft = await _load_draft(db, draft_id, owner_id)
    return await _undo_edit_impl(
        db, draft=draft, owner_id=owner_id, edit_id=edit_id,
        new_id_factory=_new_id,
    )


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------


async def promote_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    mode: str,
    new_title: str | None = None,
) -> str:
    """Save draft state to a real ruleset. Returns the resulting ruleset_id.

    Draft is **kept** after promote so the user can keep iterating.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    parsed_v6 = copy.deepcopy(draft.parsed_v6 or empty_v6())

    # B1: refuse promote when core_rules is empty or still the
    # bootstrap placeholder -- the V6 parser used by the game runtime
    # requires real core content, and silently promoting would create
    # an unplayable ruleset.
    core_rules_text = str(parsed_v6.get("core_rules") or "").strip()
    if not core_rules_text or "call design_core_rules" in core_rules_text:
        raise HTTPException(
            400,
            "core_rules is empty or still the bootstrap placeholder -- "
            "call design_core_rules with real content before promoting",
        )

    dice_ir = parsed_v6.pop("dice_ir", None) if isinstance(parsed_v6, dict) else None
    character_ui = (
        parsed_v6.pop("character_ui", None) if isinstance(parsed_v6, dict) else None
    )

    # Stamp a slim manifest into parsed_v6 so the export path can ship
    # it alongside the published artifact (chatlab parity). The
    # promote-time snapshot captures the draft's state at the moment
    # it became authoritative; agents reading the published ruleset
    # later see the same index.
    from services.draft_manifest import build_draft_manifest
    promote_input = dict(parsed_v6)
    if dice_ir is not None:
        promote_input["dice_ir"] = dice_ir
    parsed_v6["knowledge_manifest"] = build_draft_manifest(promote_input)

    if mode == "target":
        if not draft.target_ruleset_id:
            raise HTTPException(400, "Draft has no target ruleset")
        rs = await _load_owned_ruleset(db, draft.target_ruleset_id, owner_id)
        rs.parsed_v6 = copy.deepcopy(parsed_v6)
        flag_modified(rs, "parsed_v6")
        rs.book_id = str(parsed_v6.get("book_id") or "")
        rs.book_title = str(parsed_v6.get("book_title") or "")
        rs.world_mode = str(parsed_v6.get("world_mode") or "")
        if dice_ir is not None:
            rs.dice_ir = dice_ir
        if character_ui is not None:
            rs.character_ui = character_ui
        rs.updated_at = _now()
        await db.commit()
        return rs.id

    # mode == "new"
    rs = Ruleset(
        id=_new_id("rs"),
        owner_id=owner_id,
        is_shared=False,
        book_id=str(parsed_v6.get("book_id") or ""),
        book_title=(new_title or str(parsed_v6.get("book_title") or draft.title)),
        world_mode=str(parsed_v6.get("world_mode") or ""),
        parsed_v6=copy.deepcopy(parsed_v6),
        dice_ir=dice_ir,
        character_ui=character_ui,
        check_spec=None,
        notes="",
    )
    db.add(rs)
    await db.commit()
    await db.refresh(rs)
    return rs.id


# ---------------------------------------------------------------------------
# Message persistence (used by P3 agent loop)
# ---------------------------------------------------------------------------


async def append_message(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    role: str,
    content: dict[str, Any],
    kind: str = "main",
) -> RulesetDraftMessage:
    """Persist one transcript row. `kind` selects which agent pane
    owns the row -- "main" or "dice". Seq is monotonic per draft
    across BOTH kinds so stable ordering works for any combined view.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    last = await db.execute(
        select(RulesetDraftMessage.seq)
        .where(RulesetDraftMessage.draft_id == draft.id)
        .order_by(RulesetDraftMessage.seq.desc())
        .limit(1)
    )
    last_seq = last.scalar() or 0
    msg = RulesetDraftMessage(
        id=_new_id("msg"),
        draft_id=draft.id,
        seq=last_seq + 1,
        role=role,
        kind=kind,
        content=content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


def patch_error_to_http(e: PatchError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error_code": e.code,
            "message": e.message,
            "op_index": e.op_index,
        },
    )
