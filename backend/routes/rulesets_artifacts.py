"""Pure helper functions for ruleset artifact shaping and validation.

Extracted from `routes/rulesets.py` so the main router file can focus on
HTTP-facing concerns. None of these touch the database or schedule
background work — they read and reshape the v6/dice-IR JSON shapes that
sit in `Ruleset.parsed_v6`, `Ruleset.dice_ir`, and `Ruleset.character_ui`.

`routes.rulesets` re-exports the public-ish names from this module so
existing imports such as `from routes.rulesets import _is_compiled_artifact`
keep working.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from agents.trpg.character_ui.compile import (
    is_compiled_artifact as _ui_is_compiled,
)
from agents.trpg.check_spec_registry import public_check_spec
from orm.models import Ruleset
from schemas.ruleset import RulesetDetail, RulesetSummary


def _is_compiled_artifact(ir: dict[str, Any] | None) -> bool:
    """True only when the artifact carries an actual compiled package.

    Compiling/failed stubs (status=compiling|failed) are rejected so
    `has_dice_ir` reports the runtime-usable state rather than mere
    presence of a row.
    """
    if not isinstance(ir, dict):
        return False
    if str(ir.get("status") or "") in {"compiling", "failed"}:
        return False
    package = ir.get("package")
    if not isinstance(package, dict):
        return False
    compiled = package.get("compiled")
    return isinstance(compiled, dict) and bool(compiled.get("check_specs"))


def _compiled_block(artifact: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        return {}
    package = artifact.get("package")
    if not isinstance(package, dict):
        return {}
    compiled = package.get("compiled")
    return compiled if isinstance(compiled, dict) else {}


def _pick_compiled_check_spec(
    artifact: dict[str, Any] | None,
    procedure_id: str = "",
) -> tuple[str, dict[str, Any] | None]:
    compiled = _compiled_block(artifact)
    candidates = compiled.get("check_specs") or []
    wanted = procedure_id or str(compiled.get("default_procedure_id") or "")
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("procedure_id") or "")
        if wanted and entry_id != wanted:
            continue
        spec = entry.get("check_spec")
        if isinstance(spec, dict):
            return entry_id, public_check_spec(spec)
    if candidates:
        first = candidates[0]
        if isinstance(first, dict) and isinstance(first.get("check_spec"), dict):
            return str(first.get("procedure_id") or ""), public_check_spec(first["check_spec"])
    return "", None


def _mark_applied_check_spec(
    artifact: dict[str, Any],
    *,
    procedure_id: str,
    check_spec: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    out = deepcopy(artifact)
    out["applied_check_spec"] = {
        "procedure_id": procedure_id,
        "engine": str(check_spec.get("engine") or ""),
        "source": source,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    return out


def _summary(rs: Ruleset) -> RulesetSummary:
    return RulesetSummary(
        id=rs.id,
        owner_id=rs.owner_id,
        is_shared=bool(rs.is_shared),
        book_id=rs.book_id,
        book_title=rs.book_title,
        world_mode=rs.world_mode,
        has_dice_ir=_is_compiled_artifact(rs.dice_ir),
        has_check_spec=bool(rs.check_spec),
        has_character_ui=_ui_is_compiled(rs.character_ui),
        created_at=rs.created_at,
        updated_at=rs.updated_at,
    )


def _detail(rs: Ruleset) -> RulesetDetail:
    return RulesetDetail(
        id=rs.id,
        owner_id=rs.owner_id,
        is_shared=bool(rs.is_shared),
        book_id=rs.book_id,
        book_title=rs.book_title,
        world_mode=rs.world_mode,
        has_dice_ir=_is_compiled_artifact(rs.dice_ir),
        has_check_spec=bool(rs.check_spec),
        has_character_ui=_ui_is_compiled(rs.character_ui),
        created_at=rs.created_at,
        updated_at=rs.updated_at,
        parsed_v6=rs.parsed_v6,
        dice_ir=rs.dice_ir,
        check_spec=rs.check_spec,
        character_ui=rs.character_ui,
    )


def _can_see(rs: Ruleset, user_id: str) -> bool:
    return bool(rs.is_shared) or rs.owner_id == user_id


def _validate_v6(artifact: dict[str, Any]) -> None:
    """Light shape check — the frontend already validates, this is defense in depth."""
    if not isinstance(artifact, dict):
        raise HTTPException(400, "artifact must be a JSON object")
    version = artifact.get("version")
    looks_like_v6 = (
        isinstance(artifact.get("core_rules"), str)
        and isinstance(artifact.get("rule_packages"), list)
        and isinstance(artifact.get("parameter_families"), list)
    )
    if version != 6 and not looks_like_v6:
        raise HTTPException(400, f"Unsupported ruleset version: {version}")
    if not isinstance(artifact.get("core_rules"), str) or not artifact["core_rules"].strip():
        raise HTTPException(400, "Missing core_rules content")


def _build_compile_markdown(parsed_v6: dict[str, Any]) -> str:
    """Concatenate the rule sections into a single markdown blob for compile.

    The compiler reads the rulebook holistically — it needs to see core +
    companion + every scenario package together to emit a coherent set of
    executable check IR procedures.
    """
    parts: list[str] = []
    core = parsed_v6.get("core_rules") or ""
    if core:
        parts.append(str(core))

    companion = parsed_v6.get("companion") or {}
    if isinstance(companion, dict) and isinstance(companion.get("content"), str):
        parts.append(str(companion["content"]))

    for pkg in parsed_v6.get("rule_packages") or []:
        if not isinstance(pkg, dict):
            continue
        content = pkg.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content)

    return "\n\n".join(parts).strip()


def _extract_embedded_dice_ir(artifact: dict[str, Any]) -> dict[str, Any] | None:
    """Pull a dice_ir artifact out of an uploaded v6 JSON if it has one.

    Three known locations, in priority order:
      - top-level ``dice_ir`` (chatrpg fixtures + new chatlab serialize_v6)
      - ``parse_artifacts.v6.dice_ir`` (post-stage-8 chatlab DB shape)
      - ``parse_artifacts.dice_ir_compiler`` (legacy chatlab top-level key)
    """
    candidates: list[Any] = []
    if isinstance(artifact.get("dice_ir"), dict) and artifact["dice_ir"]:
        candidates.append(artifact["dice_ir"])
    pa = artifact.get("parse_artifacts")
    if isinstance(pa, dict):
        v6 = pa.get("v6")
        if isinstance(v6, dict) and isinstance(v6.get("dice_ir"), dict) and v6["dice_ir"]:
            candidates.append(v6["dice_ir"])
        legacy = pa.get("dice_ir_compiler")
        if isinstance(legacy, dict) and legacy:
            candidates.append(legacy)
    for candidate in candidates:
        if isinstance(candidate, dict) and _is_compiled_artifact(candidate):
            return candidate
    return None


def _build_compiling_stub(*, model: str, output_language: str) -> dict[str, Any]:
    """In-flight marker for the dice_ir column while the compile runs.

    Mirrors the shape the frontend reads so it can render a "compiling"
    state without needing a separate column.
    """
    return {
        "status": "compiling",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "output_language": output_language,
        "auto_compiled": True,
    }


def _build_failed_stub(
    *, model: str, output_language: str, error: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "output_language": output_language,
        "error": error,
        "auto_compiled": True,
    }
