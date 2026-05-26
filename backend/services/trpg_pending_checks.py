"""Pending-check helpers for chatrpg's auto/pending [CHECK] split.

The `[pending_check ...]` placeholder is what the GM emits when a
non-combat check is requested
without `auto=true`. The frontend turns it into a "投出" button card; when
the player clicks, the chat-stream endpoint parses the placeholder back via
`parse_pending_check`, calls the unified CHECK runtime to roll and resolve,
replaces the placeholder in the source GM message with the resolved `[dice]`
block, and runs an IC continuation turn so the GM narrates the consequence.

Splitting this into its own module (rather than expanding `trpg_ic_markers`)
keeps the responsibility boundary clean: `trpg_ic_markers` is for markers
that produce session-state side effects; `trpg_pending_checks` is for the
in-message placeholder ↔ dice-block lifecycle.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from agents.trpg.check_actor_adapter import (
    ActorLookupContext,
    apply_actor_value_lookup,
    build_actor_lookup_context,
)
from agents.trpg.check_inline import _ATTR_RE
from agents.trpg.check_runtime import CheckExecution, execute_check_runtime
from agents.trpg.check_resolver import (
    CheckArgs,
    coerce_int,
)
from orm.models import GameSession, Message
from services.trpg_check_logs import record_check_execution

logger = logging.getLogger("chatrpg.trpg")


_PLACEHOLDER_RE = re.compile(r"\[pending_check\s+([^\]]*)\]", re.IGNORECASE)


@dataclass
class PendingCheck:
    """Parsed `[pending_check ...]` placeholder, ready for the resolver."""

    id: str
    engine: str
    procedure_id: str
    skill: str
    value: int | None
    difficulty: str
    target: int | None
    pool: str
    bonus: int
    penalty: int
    reason: str
    raw_match: str  # the full `[pending_check ...]` literal, for replacement
    roll_seed: str = ""
    actor: str = ""
    check: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_args(self) -> CheckArgs:
        roll_seed = self.roll_seed or f"pending:{self.id}"
        skill_label = self.skill or self.check
        return CheckArgs(
            skill=skill_label,
            value=self.value,
            roll=None,
            difficulty=self.difficulty or "regular",
            bonus=self.bonus or 0,
            penalty=self.penalty or 0,
            pool=self.pool,
            target=self.target,
            reason=self.reason,
            extras={
                **dict(self.extras or {}),
                "procedure_id": self.procedure_id,
                "roll_seed": roll_seed,
                **({"actor": self.actor} if self.actor else {}),
                **({"check": self.check} if self.check else {}),
            },
        )

    def to_metadata(self) -> dict[str, Any]:
        """Compact dict for `gm_message_metadata.pending_checks[]`."""
        return {
            "id": self.id,
            "engine": self.engine,
            "procedure_id": self.procedure_id,
            "skill": self.skill,
            "value": self.value,
            "difficulty": self.difficulty,
            "target": self.target,
            "pool": self.pool,
            "bonus": self.bonus,
            "penalty": self.penalty,
            "reason": self.reason,
            "roll_seed": self.roll_seed or f"pending:{self.id}",
            "actor": self.actor,
            "check": self.check,
            "extras": dict(self.extras or {}),
            "resolved": False,
        }


def _coerce_int(raw: str) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_attrs(payload: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(payload or ""):
        key = m.group("key").lower()
        val = (
            m.group("qval")
            or m.group("sval")
            or m.group("bval")
            or ""
        )
        out[key] = val
    return out


def _build_from_attrs(attrs: dict[str, str], raw_match: str) -> PendingCheck | None:
    pid = (attrs.get("id") or "").strip()
    if not pid:
        return None
    return PendingCheck(
        id=pid,
        engine=(attrs.get("engine") or "custom_llm").strip().lower(),
        procedure_id=(attrs.get("procedure_id") or "").strip(),
        skill=attrs.get("skill", ""),
        value=_coerce_int(attrs.get("value", "")),
        difficulty=(attrs.get("difficulty") or "regular").strip().lower(),
        target=_coerce_int(attrs.get("target", "")),
        pool=attrs.get("pool", ""),
        bonus=_coerce_int(attrs.get("bonus", "")) or 0,
        penalty=_coerce_int(attrs.get("penalty", "")) or 0,
        reason=attrs.get("reason", ""),
        raw_match=raw_match,
        roll_seed=(attrs.get("roll_seed") or attrs.get("seed") or "").strip(),
        actor=(
            attrs.get("actor")
            or attrs.get("actor_id")
            or attrs.get("npc_key")
            or ""
        ).strip(),
        check=(
            attrs.get("check")
            or attrs.get("check_key")
            or attrs.get("param")
            or ""
        ).strip(),
        extras=_pending_extras(attrs),
    )


_PENDING_BASE_ATTRS = {
    "id",
    "engine",
    "roll_seed",
    "seed",
    "procedure_id",
    "skill",
    "value",
    "difficulty",
    "target",
    "pool",
    "bonus",
    "penalty",
    "reason",
    "roll",
    "auto",
    "actor",
    "actor_id",
    "npc_key",
    "check",
    "check_key",
    "param",
}
_SAFE_PENDING_EXTRA_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _pending_extras(attrs: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key in _PENDING_BASE_ATTRS or key.startswith("_"):
            continue
        if not _SAFE_PENDING_EXTRA_KEY_RE.match(key):
            continue
        if value in (None, ""):
            continue
        out[key] = _coerce_pending_extra(value)
    return out


def _coerce_pending_extra(raw: str) -> Any:
    text = str(raw or "").strip()
    if text.startswith("json64:"):
        try:
            return json.loads(_b64_url_decode(text[7:]))
        except (ValueError, TypeError):
            return text
    if text.startswith("str64:"):
        try:
            return _b64_url_decode(text[6:])
        except (ValueError, TypeError):
            return text
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _b64_url_decode(text: str) -> str:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def find_pending_checks(text: str) -> list[PendingCheck]:
    """Return every `[pending_check ...]` placeholder in `text`, in order."""
    if not text:
        return []
    out: list[PendingCheck] = []
    for m in _PLACEHOLDER_RE.finditer(text):
        attrs = _parse_attrs(m.group(1) or "")
        pending = _build_from_attrs(attrs, m.group(0))
        if pending is not None:
            out.append(pending)
    return out


def parse_pending_check(text: str, *, check_id: str) -> PendingCheck | None:
    """Locate a single placeholder in `text` by `id`. None if missing."""
    target = (check_id or "").strip()
    if not target:
        return None
    for pending in find_pending_checks(text):
        if pending.id == target:
            return pending
    return None


def resolve_pending_execution(
    pending: PendingCheck,
    spec: dict[str, Any] | None,
    *,
    auto_roll: Any = None,
    actor_context: ActorLookupContext | dict[str, Any] | None = None,
) -> CheckExecution:
    """Roll `pending` through the unified runtime and return full execution.

    When ``auto_roll`` is provided, it is used as the already-rolled value.
    Otherwise the runtime generates dice at the same boundary as inline
    ``[CHECK auto=true]`` resolution."""
    args = pending.to_args()
    should_auto_roll = True
    if auto_roll is not None:
        args.roll = auto_roll
        should_auto_roll = False
    args = apply_actor_value_lookup(args, actor_context)
    execution = execute_check_runtime(
        args,
        spec or {"engine": pending.engine},
        procedure_id=pending.procedure_id,
        system=pending.engine,
        auto_roll=should_auto_roll,
        source="pending_check_resolve",
    )
    if execution.result.warnings:
        for w in execution.result.warnings:
            logger.info("[TRPG] pending_check resolve warning: %s", w)
    return execution


def resolve_pending(
    pending: PendingCheck,
    spec: dict[str, Any] | None,
    *,
    auto_roll: Any,
) -> str:
    """Backwards-compatible helper returning only the rendered dice block."""

    return resolve_pending_execution(
        pending,
        spec,
        auto_roll=auto_roll,
    ).rendered


async def resolve_all_pending_in_session(
    db: AsyncSession,
    session: GameSession,
    ruleset_check_spec: dict[str, Any] | None,
    *,
    pending_check_id: str | None = None,
    auto_roll: Any = None,
) -> list[dict[str, Any]]:
    """Resolve unresolved `[pending_check ...]` entries in the latest GM
    message of `session`. If `pending_check_id` is supplied, only that entry
    is touched. For each resolved entry:

    1. Parse the placeholder, build a CheckArgs, and resolve it. If
       `auto_roll` is supplied for the selected pending id, use that already
       rolled value; otherwise auto-roll using the same `check_runtime`
       boundary as inline auto-resolve.
    2. Persist a `role=dice` message holding the rendered `[dice]` block.
    3. Mutate the source GM message's content: replace the
       `[pending_check ...]` literal with the rendered `[dice]` block.
    4. Mark `metadata.pending_checks[*].resolved = True` on the GM message.

    Returns one summary dict per resolved check (id, summary line, total).
    Caller is responsible for `db.commit()`.

    If no GM message has pending checks, returns an empty list — caller can
    treat that as "nothing to resolve, just continue the turn."""
    import uuid as _uuid

    # Find the most recent GM message; bail if it has no placeholders.
    stmt = (
        select(Message)
        .where(Message.session_id == session.id)
        .where(Message.role == "gm")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    gm_msg = (await db.execute(stmt)).scalars().first()
    if gm_msg is None:
        return []
    pending_list = find_pending_checks(gm_msg.content or "")
    if not pending_list:
        return []

    summaries: list[dict[str, Any]] = []
    new_content = gm_msg.content or ""
    md = dict(gm_msg.metadata_json or {})
    md_pending = md.get("pending_checks")
    if not isinstance(md_pending, list):
        md_pending = []

    target_id = (pending_check_id or "").strip()

    for pending in pending_list:
        if target_id and pending.id != target_id:
            continue
        # Skip if metadata already says resolved (idempotent retry).
        idx = next(
            (i for i, e in enumerate(md_pending)
             if isinstance(e, dict) and str(e.get("id") or "") == pending.id),
            None,
        )
        if idx is not None and md_pending[idx].get("resolved"):
            continue

        manual_roll = auto_roll
        execution = resolve_pending_execution(
            pending,
            ruleset_check_spec or {"engine": pending.engine},
            auto_roll=manual_roll,
            actor_context=build_actor_lookup_context(session),
        )
        if not target_id:
            auto_roll = None
        rendered = execution.rendered
        trace_meta = execution.trace.to_metadata()

        # Replace placeholder text inside the source GM message.
        new_content = new_content.replace(pending.raw_match, rendered, 1)

        # Persist a dice message in its own row so the side panel + future
        # turns can read it.
        dice_meta = summarize_for_dice_message(pending, execution)
        dice_msg = Message(
            id=str(_uuid.uuid4()),
            session_id=session.id,
            role="dice",
            content=rendered,
            metadata_json=dice_meta,
        )
        db.add(dice_msg)
        await db.flush()
        request_meta = _request_payload(pending)
        result_meta = _result_payload(execution)
        check_log = record_check_execution(
            db,
            session,
            execution,
            message_id=dice_msg.id,
            actor_id=pending.actor,
            source="pending_check_resolve",
            request_json=request_meta,
            result_json=result_meta,
            runtime_spec=ruleset_check_spec,
        )
        dice_meta["check_log_id"] = check_log.id
        dice_meta["result_detail"] = dict(check_log.result_json or result_meta)
        dice_meta["trace"] = dict(check_log.trace_json or trace_meta)
        if (check_log.result_json or {}).get("rule_consequences"):
            dice_meta["rule_consequences"] = list(
                (check_log.result_json or {}).get("rule_consequences") or []
            )
        dice_msg.metadata_json = dict(dice_meta)
        flag_modified(dice_msg, "metadata_json")

        # Mark resolved in metadata for this GM message.
        if idx is not None:
            md_pending[idx]["resolved"] = True
            md_pending[idx]["result"] = dice_meta.get("result")
            md_pending[idx]["check_log_id"] = check_log.id
        else:
            md_pending.append({
                **pending.to_metadata(),
                "resolved": True,
                "result": dice_meta.get("result"),
                "check_log_id": check_log.id,
            })

        summaries.append({
            "id": pending.id,
            "skill": pending.skill,
            "result": dice_meta.get("result"),
            "trace": dice_meta.get("trace") or trace_meta,
            "rule_consequences": (check_log.result_json or {}).get("rule_consequences") or [],
            "check_log_id": check_log.id,
        })

    if summaries:
        gm_msg.content = new_content
        md["pending_checks"] = md_pending
        gm_msg.metadata_json = md
        flag_modified(gm_msg, "metadata_json")
    return summaries


def summarize_for_dice_message(
    pending: PendingCheck,
    execution: CheckExecution,
) -> dict[str, Any]:
    """Metadata payload for the `role=dice` message persisted on resolve."""
    label = pending.skill or "Roll"
    trace = execution.trace.to_metadata()
    roll_value = trace.get("roll_total")
    request_meta = _request_payload(pending)
    result_meta = _result_payload(execution)
    return {
        "type": label,
        "result": coerce_int(roll_value, 0) if roll_value is not None else 0,
        "engine": trace.get("engine") or pending.engine,
        "procedure_id": trace.get("procedure_id") or pending.procedure_id,
        "request": request_meta,
        "result_detail": result_meta,
        "warnings": trace.get("warnings") or [],
        "reason": pending.reason,
        "source": "pending_check_resolve",
        "pending_check_id": pending.id,
        "seed": trace.get("roll_seed") or pending.roll_seed,
        "roll_trace": trace.get("roll_trace") or {},
        "trace": trace,
    }


def _request_payload(pending: PendingCheck) -> dict[str, Any]:
    return {
        "id": pending.id,
        "engine": pending.engine,
        "procedure_id": pending.procedure_id,
        "skill": pending.skill,
        "value": pending.value,
        "difficulty": pending.difficulty,
        "target": pending.target,
        "pool": pending.pool,
        "bonus": pending.bonus,
        "penalty": pending.penalty,
        "reason": pending.reason,
        "roll_seed": pending.roll_seed or f"pending:{pending.id}",
        "actor": pending.actor,
        "check": pending.check,
        "extras": dict(pending.extras or {}),
    }


def _result_payload(execution: CheckExecution) -> dict[str, Any]:
    result = execution.result
    return {
        "tier": result.tier,
        "tier_label": result.tier_label,
        "passed": result.passed,
        "explanation": result.explanation,
        "thresholds": dict(result.thresholds or {}),
        "warnings": list(result.warnings or []),
        "engine": result.engine,
        "side_effects": dict(result.side_effects or {}),
        "result_axes": dict(result.result_axes or {}),
        "roll_display": result.roll_display,
    }
