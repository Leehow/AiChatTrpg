"""Background runner for module semantic parsing."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session_factory
from orm.models import ParsedModule
from services import module_semantic

logger = logging.getLogger("chatrpg.module_semantic")
_TASKS: set[asyncio.Task] = set()


async def prepare_semantic_parse(
    db: AsyncSession,
    row: ParsedModule,
) -> ParsedModule:
    seed = module_semantic.seed_steps(
        row.markdown, row.toc or [], row.toc_source or "heuristic", row.filename
    )
    row.semantic_status = "running"
    row.semantic_error = ""
    row.semantic_structure = {}
    row.briefing_md = ""
    row.appendix_index = {"categories": [], "entries": []}
    row.semantic_steps = [*seed, _semantic_step("running", "Waiting for structure LLM")]
    await db.commit()
    await db.refresh(row)
    return row


def enqueue_semantic_parse(module_id: str) -> None:
    task = asyncio.create_task(_run_semantic_parse_job(module_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _run_semantic_parse_job(module_id: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        row = await db.get(ParsedModule, module_id)
        if row is None:
            return
        seed = module_semantic.seed_steps(
            row.markdown, row.toc or [], row.toc_source or "heuristic", row.filename
        )

        async def save_progress(
            structure: dict,
            briefing_md: str,
            steps: list[dict],
        ) -> None:
            row.semantic_status = "running"
            row.semantic_error = ""
            row.semantic_structure = structure
            row.briefing_md = briefing_md
            row.semantic_steps = [
                *seed,
                _semantic_step("running", _semantic_progress_summary(steps)),
                *steps,
            ]
            await db.commit()

        try:
            result = await module_semantic.parse_module_semantics(
                db, row.markdown, row.toc or [], row.filename,
                on_progress=save_progress,
            )
            row.semantic_status = result.status
            row.semantic_error = result.error
            row.semantic_structure = result.structure
            row.briefing_md = result.briefing_md
            row.appendix_index = result.appendix_index
            row.semantic_steps = [
                *seed,
                _semantic_step(result.status, _semantic_result_summary(result)),
                *result.steps,
            ]
        except Exception as exc:  # pragma: no cover
            logger.exception("module semantic parse failed for %s", module_id)
            row.semantic_status = "error"
            row.semantic_error = f"{type(exc).__name__}: {exc}"
            row.semantic_steps = [
                *seed,
                _semantic_step("error", row.semantic_error),
            ]
        await db.commit()


def _semantic_step(status: str, summary: str) -> dict:
    return module_semantic.step("semantic_parse", status, summary, {})


def _semantic_progress_summary(steps: list[dict]) -> str:
    stages = {str(item.get("stage", "")) for item in steps if isinstance(item, dict)}
    if "appendix_index" in stages:
        return "Finishing appendix index"
    if "briefing" in stages:
        return "Briefing ready; indexing appendices"
    if "2.1_structure" in stages:
        return "Structure ready; splitting playable blocks"
    return "Waiting for structure LLM"


def _semantic_result_summary(result: module_semantic.SemanticParseResult) -> str:
    if result.status == "done":
        sections = len(result.structure.get("sections", []))
        playable = len(result.structure.get("playable_units", []))
        return f"Completed with {sections} sections and {playable} playable blocks"
    return result.error or "Semantic parse failed"
