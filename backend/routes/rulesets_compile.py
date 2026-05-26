"""Ruleset compile orchestration: background tasks, single-column writers,
default-compiler resolution, and the shared `_create_ruleset_from_artifact`
helper used by both `POST /api/rulesets` and `POST /api/rulesets/file`.

Extracted from `routes/rulesets.py` so the main router file fits under the
600-line policy and so engine-shaped helpers (DB writes + LLM compile
glue) live separately from request handlers. `routes.rulesets` re-exports
the public-ish names so existing imports such as
`from routes.rulesets import _resolve_default_compiler_config` keep
working.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.character_ui import (
    CharacterUICompilerError,
    compile_character_ui,
)
from agents.trpg.character_ui.compile import (
    build_compiling_stub as _ui_build_compiling_stub,
    build_failed_stub as _ui_build_failed_stub,
    is_compiled_artifact as _ui_is_compiled,
)
from agents.trpg.check_ir.compile_direct import (
    DEFAULT_DICE_COMPILER_MODEL,
    compile_to_ir_direct,
)
from agents.trpg.pipeline_helpers import resolve_compiler_api_config
from core.database import get_session_factory
from orm.models import Ruleset, User
from routes.rulesets_artifacts import (
    _build_compile_markdown,
    _build_compiling_stub,
    _build_failed_stub,
    _detail,
    _extract_embedded_dice_ir,
    _is_compiled_artifact,
    _mark_applied_check_spec,
    _pick_compiled_check_spec,
    _validate_v6,
)
from schemas.ruleset import RulesetDetail
from services import admin_config, model_pool

logger = logging.getLogger("chatrpg.rulesets")


async def _set_dice_ir(ruleset_id: str, owner_id: str, value: Any) -> None:
    """Atomic single-column UPDATE on rulesets.dice_ir, owner-scoped."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Ruleset)
            .where(Ruleset.id == ruleset_id, Ruleset.owner_id == owner_id)
            .values(dice_ir=value)
        )
        await session.commit()


async def _set_dice_ir_and_check_spec(
    ruleset_id: str,
    owner_id: str,
    dice_ir: Any,
    check_spec: dict[str, Any] | None,
) -> None:
    """Atomic UPDATE for compile completion, including runtime default spec."""
    values: dict[str, Any] = {"dice_ir": dice_ir}
    if check_spec is not None:
        values["check_spec"] = check_spec
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Ruleset)
            .where(Ruleset.id == ruleset_id, Ruleset.owner_id == owner_id)
            .values(**values)
        )
        await session.commit()


async def _set_character_ui(
    ruleset_id: str, owner_id: str, value: Any,
) -> None:
    """Atomic single-column UPDATE on rulesets.character_ui, owner-scoped."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Ruleset)
            .where(Ruleset.id == ruleset_id, Ruleset.owner_id == owner_id)
            .values(character_ui=value)
        )
        await session.commit()


def _provider_default_key(provider: str) -> str:
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


async def _resolve_default_compiler_config(
    db: AsyncSession,
) -> dict[str, str]:
    """Resolve compiler model/base_url/api_key from the model pool's default
    entry, falling back to the dice compiler defaults if the pool is empty.

    The character UI compiler should respect the user's chosen default model
    rather than always using the hardcoded dice-compiler default — the user
    set that dropdown for a reason.
    """
    entry = await model_pool.get_default(db)
    if entry is not None:
        saved = admin_config.get_provider(entry.provider) or {}
        api_key = (
            saved.get("api_key", "")
            or _provider_default_key(entry.provider)
        )
        base_url = (
            saved.get("base_url", "")
            or _provider_default_base_url(entry.provider)
        )
        if api_key and base_url:
            return {
                "model": entry.model,
                "base_url": base_url.rstrip("/"),
                "api_key": api_key,
            }
    # Pool empty or its entry has no saved API config — fall back to the
    # codex-relay defaults baked into the dice compiler.
    return resolve_compiler_api_config(model=DEFAULT_DICE_COMPILER_MODEL)


async def _run_character_ui_compile_background(
    ruleset_id: str, owner_id: str,
) -> None:
    """Compile the character_sheet UI schema in the background after upload.

    Mirrors `_run_dice_ir_compile_background` — same compiling/failed stub
    pattern, separate column. Uses the model pool's default entry so users
    can switch the compiler model from the model settings page.
    """
    factory = get_session_factory()
    async with factory() as session:
        rs = await session.get(Ruleset, ruleset_id)
        if rs is None or rs.owner_id != owner_id:
            return
        if _ui_is_compiled(rs.character_ui):
            return
        if not isinstance(rs.parsed_v6, dict):
            return
        cs = rs.parsed_v6.get("character_sheet")
        if not isinstance(cs, dict) or not isinstance(
            cs.get("template_json"), dict,
        ):
            logger.info(
                "[chatrpg] character_ui auto-compile skipped: "
                "ruleset %s has no template_json", ruleset_id,
            )
            return
        cfg = await _resolve_default_compiler_config(session)

    if not cfg.get("api_key"):
        await _set_character_ui(
            ruleset_id, owner_id,
            _ui_build_failed_stub(
                model=cfg.get("model") or "",
                error="No api_key configured for default compiler model",
            ),
        )
        return

    await _set_character_ui(
        ruleset_id, owner_id,
        _ui_build_compiling_stub(model=cfg["model"]),
    )

    try:
        # Re-fetch parsed_v6 in a fresh session — the original session was
        # closed above to free its connection during the LLM call.
        factory = get_session_factory()
        async with factory() as session:
            rs = await session.get(Ruleset, ruleset_id)
            if rs is None or rs.owner_id != owner_id:
                return
            parsed_v6 = rs.parsed_v6 or {}
            book_title = rs.book_title or ""

        artifact = await compile_character_ui(
            parsed_v6,
            book_title=book_title,
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            # Pull the language hint from the v6 artifact so labels match
            # the language the player parsed the rulebook in.
            output_language=str(parsed_v6.get("output_language") or "en"),
        )
    except CharacterUICompilerError as exc:
        logger.warning(
            "[chatrpg] character_ui compile failed (validation) "
            "ruleset=%s: %s", ruleset_id, exc,
        )
        await _set_character_ui(
            ruleset_id, owner_id,
            _ui_build_failed_stub(model=cfg["model"], error=str(exc)),
        )
        return
    except Exception as exc:  # noqa: BLE001 - background task swallow
        logger.exception(
            "[chatrpg] character_ui compile failed ruleset=%s", ruleset_id,
        )
        await _set_character_ui(
            ruleset_id, owner_id,
            _ui_build_failed_stub(
                model=cfg["model"],
                error=f"{type(exc).__name__}: {exc}",
            ),
        )
        return

    await _set_character_ui(ruleset_id, owner_id, artifact)
    package = artifact.get("package") or {}
    widgets = package.get("widgets") if isinstance(package, dict) else []
    logger.info(
        "[chatrpg] character_ui compile done ruleset=%s widgets=%d",
        ruleset_id, len(widgets) if isinstance(widgets, list) else 0,
    )


async def _run_dice_ir_compile_background(ruleset_id: str, owner_id: str) -> None:
    """Run the dice IR compiler in the background after upload.

    Opens its own AsyncSession so it survives past the request scope.
    Writes a ``status=compiling`` stub at start and either the full
    compiled artifact on success, or a ``status=failed`` stub on error,
    so the UI can render an in-flight / retryable state.
    """
    factory = get_session_factory()
    async with factory() as session:
        rs = await session.get(Ruleset, ruleset_id)
        if rs is None or rs.owner_id != owner_id:
            logger.warning(
                "[chatrpg] auto-compile aborted: ruleset %s not found / wrong owner",
                ruleset_id,
            )
            return
        if _is_compiled_artifact(rs.dice_ir):
            logger.info(
                "[chatrpg] auto-compile skipped: ruleset %s already has dice_ir",
                ruleset_id,
            )
            return

        markdown = _build_compile_markdown(rs.parsed_v6 or {})
        if not markdown:
            logger.warning(
                "[chatrpg] auto-compile skipped: ruleset %s has no compilable content",
                ruleset_id,
            )
            return

        cfg = resolve_compiler_api_config(model=DEFAULT_DICE_COMPILER_MODEL)
        if not cfg.get("api_key"):
            logger.warning(
                "[chatrpg] auto-compile skipped: no api_key for compiler model %s",
                cfg.get("model"),
            )
            await _set_dice_ir(
                ruleset_id, owner_id,
                _build_failed_stub(
                    model=cfg.get("model") or "",
                    output_language="en",
                    error="No api_key configured for compiler model",
                ),
            )
            return

        output_language = (rs.parsed_v6.get("output_language") or "en").lower()
        if output_language not in {"en", "zh"}:
            output_language = "en"

        logger.info(
            "[chatrpg] auto-compile start ruleset=%s book=%s model=%s lang=%s",
            ruleset_id, rs.book_title, cfg["model"], output_language,
        )

    # Release the session held during the marker write so the long LLM
    # call doesn't pin a DB connection for minutes.
    await _set_dice_ir(
        ruleset_id, owner_id,
        _build_compiling_stub(model=cfg["model"], output_language=output_language),
    )

    try:
        package = await compile_to_ir_direct(
            markdown,
            system_name=rs.book_title,
            house_rules="",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=output_language,
        )
    except Exception as exc:
        logger.exception(
            "[chatrpg] auto-compile failed ruleset=%s", ruleset_id,
        )
        await _set_dice_ir(
            ruleset_id, owner_id,
            _build_failed_stub(
                model=cfg["model"],
                output_language=output_language,
                error=f"{type(exc).__name__}: {exc}"[:500],
            ),
        )
        return

    artifact = {
        "schema_version": "ruleset_dice_ir_compiler_artifact_v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "model": package.get("model") or cfg["model"],
        "output_language": output_language,
        "package": package,
        "auto_compiled": True,
    }
    procedure_id, check_spec = _pick_compiled_check_spec(artifact)
    if check_spec is not None:
        artifact = _mark_applied_check_spec(
            artifact,
            procedure_id=procedure_id,
            check_spec=check_spec,
            source="auto_default",
        )
    await _set_dice_ir_and_check_spec(ruleset_id, owner_id, artifact, check_spec)
    compiled = (package.get("compiled") or {}) if isinstance(package, dict) else {}
    specs = compiled.get("check_specs") if isinstance(compiled, dict) else []
    logger.info(
        "[chatrpg] auto-compile done ruleset=%s specs=%d",
        ruleset_id, len(specs) if isinstance(specs, list) else 0,
    )


async def _create_ruleset_from_artifact(
    artifact: dict[str, Any],
    *,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    user: User,
) -> RulesetDetail:
    _validate_v6(artifact)

    book_id = str(artifact.get("book_id") or "")
    book_title = str(artifact.get("book_title") or "Untitled")
    world_mode = str(artifact.get("world_mode") or "")

    embedded_ir = _extract_embedded_dice_ir(artifact)

    initial_dice_ir: dict[str, Any] | None
    initial_check_spec: dict[str, Any] | None = None
    if embedded_ir is not None:
        initial_dice_ir = embedded_ir
        procedure_id, initial_check_spec = _pick_compiled_check_spec(initial_dice_ir)
        if initial_check_spec is not None:
            initial_dice_ir = _mark_applied_check_spec(
                initial_dice_ir,
                procedure_id=procedure_id,
                check_spec=initial_check_spec,
                source="auto_embedded_default",
            )
    else:
        # Write a compiling stub up front so the UI shows in-flight status
        # the instant the upload returns, without needing the background
        # task to win a race with the user's first poll.
        cfg = resolve_compiler_api_config(model=DEFAULT_DICE_COMPILER_MODEL)
        output_language = (artifact.get("output_language") or "en").lower()
        if output_language not in {"en", "zh"}:
            output_language = "en"
        initial_dice_ir = _build_compiling_stub(
            model=cfg.get("model") or DEFAULT_DICE_COMPILER_MODEL,
            output_language=output_language,
        )

    # Pre-seed a character_ui compiling stub when the ruleset carries a
    # template_json — same UI rationale as the dice-IR stub above.
    initial_character_ui: dict[str, Any] | None = None
    cs = artifact.get("character_sheet") if isinstance(artifact, dict) else None
    has_template = (
        isinstance(cs, dict) and isinstance(cs.get("template_json"), dict)
        and bool(cs["template_json"])
    )
    if has_template:
        ui_cfg = await _resolve_default_compiler_config(db)
        initial_character_ui = _ui_build_compiling_stub(
            model=ui_cfg.get("model") or DEFAULT_DICE_COMPILER_MODEL,
        )

    rs = Ruleset(
        id=str(uuid.uuid4()),
        owner_id=user.id,
        book_id=book_id,
        book_title=book_title,
        world_mode=world_mode,
        parsed_v6=artifact,
        dice_ir=initial_dice_ir,
        check_spec=initial_check_spec,
        character_ui=initial_character_ui,
    )
    db.add(rs)
    await db.commit()
    await db.refresh(rs)

    if embedded_ir is None:
        background_tasks.add_task(
            _run_dice_ir_compile_background, rs.id, user.id,
        )
    if has_template:
        background_tasks.add_task(
            _run_character_ui_compile_background, rs.id, user.id,
        )

    return _detail(rs)
