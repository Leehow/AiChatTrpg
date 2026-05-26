"""Semantic adventure parsing for uploaded module markdown."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services import module_semantic_chatlab as chatlab_steps
from services.module_npc_cards import extract_module_npc_cards
from services.module_semantic_utils import (
    build_outline,
    doc_profile,
    fallback_briefing,
    heuristic_structure,
    normalize_structure,
    step,
    structure_pipeline_steps,
)
from services.module_semantic_shape import (
    derive_global_refs,
    derive_playable_units,
)


@dataclass
class SemanticParseResult:
    status: str
    structure: dict[str, Any]
    briefing_md: str
    appendix_index: dict[str, Any]
    steps: list[dict[str, Any]]
    error: str = ""


ProgressCallback = Callable[[dict[str, Any], str, list[dict[str, Any]]], Awaitable[None]]


async def parse_module_semantics(
    db: AsyncSession,
    markdown: str,
    toc: list[dict[str, Any]],
    title_hint: str = "",
    on_progress: ProgressCallback | None = None,
) -> SemanticParseResult:
    steps: list[dict[str, Any]] = []
    try:
        outline = build_outline(markdown, toc)
        structure, source = await _parse_structure(db, markdown, outline, title_hint)
        structure = normalize_structure(structure, outline, title_hint)
        structure, rebalance_logs = await _apply_chatlab_packs(db, markdown, structure)
        steps.extend(structure_pipeline_steps(structure, source, rebalance_logs))
        await _emit_progress(on_progress, structure, "", steps)
    except Exception as exc:  # pylint: disable=broad-except
        fallback = heuristic_structure(markdown, build_outline(markdown, toc), title_hint)
        message = f"{type(exc).__name__}: {exc}"
        steps.append(step("semantic_parse", "error", message, {}))
        return SemanticParseResult(
            status="error",
            structure=fallback,
            briefing_md=fallback_briefing(fallback),
            appendix_index={"categories": [], "entries": []},
            steps=steps,
            error=message,
        )

    try:
        briefing_md, briefing_source = await _distill_briefing(
            db, markdown, outline, structure
        )
    except Exception as exc:  # pylint: disable=broad-except
        briefing_md, briefing_source = fallback_briefing(structure), "heuristic"
        steps.append(step("briefing", "error", f"{type(exc).__name__}: {exc}", {}))
    else:
        steps.append(
            step(
                "briefing",
                "done",
                f"{len(briefing_md)} characters",
                {"source": briefing_source, "briefing_md": briefing_md},
            )
        )
    structure["briefing_md"] = briefing_md
    await _emit_progress(on_progress, structure, briefing_md, steps)

    try:
        appendix_index, appendix_source = await _index_appendix(
            db, markdown, outline, structure
        )
    except Exception as exc:  # pylint: disable=broad-except
        appendix_index = {"categories": [], "entries": []}
        appendix_source = "heuristic"
        steps.append(step("appendix_index", "error", f"{type(exc).__name__}: {exc}", {}))
    else:
        entries = appendix_index.get("entries", [])
        steps.append(
            step(
                "appendix_index",
                "done",
                f"{len(entries) if isinstance(entries, list) else 0} entries",
                {"source": appendix_source, "appendix_index": appendix_index},
            )
        )
    structure["appendix_index"] = appendix_index.get("entries", [])
    structure["appendix_tables"] = appendix_index.get("tables", [])

    # NPC card extraction: clean appendix entries that look like
    # NPC/monster/creature blocks into structured ``params``. We pass an
    # empty character template here because the module is parsed in
    # isolation from any specific ruleset — the LLM uses parameter names
    # that match the source text. Sessions can re-clean later when the
    # ruleset is known if alignment is needed.
    try:
        npc_cards = await extract_module_npc_cards(
            db,
            markdown=markdown,
            appendix_entries=appendix_index.get("entries", []),
            character_template="",
        )
    except Exception as exc:  # pylint: disable=broad-except
        npc_cards = []
        steps.append(step("npc_cards", "error", f"{type(exc).__name__}: {exc}", {}))
    else:
        steps.append(
            step(
                "npc_cards",
                "done",
                f"{len(npc_cards)} card(s)",
                {"count": len(npc_cards)},
            )
        )
    structure["npc_cards"] = npc_cards
    await _emit_progress(on_progress, structure, briefing_md, steps)
    return SemanticParseResult(
        status="done",
        structure=structure,
        briefing_md=briefing_md,
        appendix_index=appendix_index,
        steps=steps,
    )


async def _emit_progress(
    on_progress: ProgressCallback | None,
    structure: dict[str, Any],
    briefing_md: str,
    steps: list[dict[str, Any]],
) -> None:
    if on_progress is not None:
        await on_progress(structure, briefing_md, steps)


def seed_steps(
    markdown: str,
    toc: list[dict[str, Any]],
    toc_source: str,
    title_hint: str = "",
) -> list[dict[str, Any]]:
    profile = doc_profile(markdown, title_hint)
    return [
        step(
            "1_preflight",
            "done",
            f"{profile['language']} / {profile['total_tokens']:,} tokens / {'has TOC' if profile['has_toc'] else 'no TOC'}",
            {"profile": profile},
        ),
        step(
            "text_extraction",
            "done",
            f"{len(markdown)} characters extracted",
            {"chars": len(markdown), "lines": len(markdown.splitlines())},
        ),
        step(
            "toc",
            "done",
            f"{len(toc)} entries from {toc_source}",
            {"source": toc_source, "toc": toc},
        ),
    ]


async def _parse_structure(
    db: AsyncSession,
    markdown: str,
    outline: list[dict[str, Any]],
    title_hint: str = "",
) -> tuple[dict[str, Any], str]:
    result = await chatlab_steps.parse_structure_llm(
        db, markdown, doc_profile(markdown, title_hint)
    )
    if not result:
        raise RuntimeError("ChatLab-compatible structure parse returned no result")
    return result, "llm"


async def _apply_chatlab_packs(
    db: AsyncSession,
    markdown: str,
    structure: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    sections = structure.get("sections", [])
    if isinstance(sections, list):
        _fill_section_counts(markdown, sections)
        if sections:
            sections[0]["start_line"] = 1
            sections[0]["line_start"] = 1
    packs = chatlab_steps.split_structure_packs(sections if isinstance(sections, list) else [])
    playable, logs = await chatlab_steps.rebalance_playable_llm(
        db, markdown, packs["playable"]
    )
    _fill_playable_aliases(playable)
    structure["packs"] = packs
    structure["playable"] = playable
    structure["playable_units"] = derive_playable_units(playable, sections)[:24]
    structure["global_refs"] = derive_global_refs(sections)
    return structure, logs


def _fill_section_counts(markdown: str, sections: list[dict[str, Any]]) -> None:
    for section in sections:
        start = int(section.get("start_line") or section.get("line_start") or 0)
        end = int(section.get("end_line") or section.get("line_end") or 0)
        lines = markdown.splitlines()
        text = "\n".join(lines[max(0, start - 1):end]).strip() if start and end else ""
        section["start_line"] = start
        section["end_line"] = end
        section["line_start"] = start
        section["line_end"] = end
        section["char_count"] = len(text)
        section["token_count"] = chatlab_steps.estimate_mixed_tokens(text)


def _fill_playable_aliases(playable: list[dict[str, Any]]) -> None:
    for section in playable:
        start = int(section.get("start_line") or section.get("line_start") or 0)
        end = int(section.get("end_line") or section.get("line_end") or 0)
        section["line_start"] = start
        section["line_end"] = end


async def _distill_briefing(
    db: AsyncSession,
    markdown: str,
    outline: list[dict[str, Any]],
    structure: dict[str, Any],
) -> tuple[str, str]:
    del outline
    packs = structure.get("packs") if isinstance(structure.get("packs"), dict) else {}
    feed = list(packs.get("other", []))
    feed.extend(
        s for s in packs.get("appendix", [])
        if isinstance(s, dict) and s.get("type") in {"appendix_rules", "appendix_others"}
    )
    text = await chatlab_steps.distill_briefing(db, markdown, feed)
    if not text:
        return fallback_briefing(structure), "heuristic"
    return text.strip(), "llm"


async def _index_appendix(
    db: AsyncSession,
    markdown: str,
    outline: list[dict[str, Any]],
    structure: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    del outline
    packs = structure.get("packs") if isinstance(structure.get("packs"), dict) else {}
    appendix_lists = [
        s for s in packs.get("appendix", [])
        if isinstance(s, dict) and s.get("type") == "appendix_list"
    ]
    raw = await chatlab_steps.index_appendix_lists(db, markdown, appendix_lists)
    tables = raw.get("tables", [])
    entries = raw.get("index", [])
    if not entries:
        return {"categories": [], "entries": []}, "heuristic"
    categories = [
        {"name": table.get("category") or table.get("source_title", ""), "count": len(table.get("entries", []))}
        for table in tables
        if isinstance(table, dict)
    ]
    return {"categories": categories, "entries": entries, "tables": tables}, "llm"
