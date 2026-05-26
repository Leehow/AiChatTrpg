"""PDF/Markdown/TXT normalized markdown -> ChatLab-style v6 ruleset JSON."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.trpg.rule_parser_v4.llm_call import TokenTracker
from agents.trpg.rule_parser_v6.preprocess import make_lined_view, make_plain_view
from agents.trpg.rule_parser_v6.stages import (
    assemble_final_manifest,
    run_character_sheet_stage,
    run_companion_stage,
    run_core_stage,
    run_dice_ir_stage,
    run_discovery_stage,
)
from agents.trpg.rule_parser_v6.stages.companion import companion_filename_for_mode
from agents.trpg.rule_parser_v6.stages.core_hooks import (
    apply_core_retrieval_hooks,
    strip_core_retrieval_hooks,
)
from agents.trpg.rule_parser_v6.stages.parameter_family import run_families
from agents.trpg.rule_parser_v6.stages.rule_package import run_packages
from services.module_parser import ModuleParseResult
from services.ocr import OCRError
from services.ruleset_parse_workflow_param_plan import apply_stage0_parameter_plan
from services.ruleset_parse_workflow_utils import (
    language as _language,
    now_iso as _now_iso,
    slug as _slug,
    title_from_filename as _title_from_filename,
)
from services.ruleset_source_compactor import prepare_ruleset_source

logger = logging.getLogger("chatrpg.ruleset_parse_workflow")


@dataclass(frozen=True)
class RulesetParseWorkflowConfig:
    model: str
    base_url: str
    api_key: str
    dice_model: str | None = None
    dice_base_url: str | None = None
    dice_api_key: str | None = None


async def run_ruleset_parse_workflow(
    parsed: ModuleParseResult,
    *,
    output_language: str | None,
    config: RulesetParseWorkflowConfig,
) -> dict[str, Any]:
    """Run ChatLab v6's stage model and return a v6 artifact JSON object."""
    markdown = (parsed.markdown or "").strip()
    if not markdown:
        raise OCRError("No text could be extracted from this ruleset file")
    if not config.api_key or not config.base_url:
        raise OCRError("No LLM API config available for ruleset parsing")

    book_title = _title_from_filename(parsed.filename)
    book_id = f"{_slug(book_title) or 'ruleset'}-{uuid.uuid4().hex[:8]}"
    world_mode = "worldview"
    lang = _language(output_language)
    original_plain = make_plain_view(markdown)
    _original_lined, original_raw_lines = make_lined_view(markdown)
    tracker = TokenTracker()
    precheck = _precheck(markdown, original_raw_lines)
    stage_model = _model_for_source_size(config.model, original_plain)
    dice_model = _model_for_source_size(config.dice_model or config.model, original_plain)
    prepared = await prepare_ruleset_source(
        markdown,
        book_title=book_title,
        output_language=lang,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
    )
    plain_view = prepared.plain_view
    lined_view = prepared.lined_view
    raw_lines = prepared.raw_lines
    prep_hint = _source_prep_hint(prepared)

    logger.info(
        "[ruleset-v6] start book=%s source_chars=%d working_chars=%d "
        "lines=%d model=%s compacted=%s",
        book_title,
        len(original_plain),
        len(plain_view),
        len(raw_lines),
        stage_model,
        prepared.compacted,
    )

    core_result = await run_core_stage(
        book_id=book_id,
        book_title=book_title,
        output_language=lang,
        book_markdown_plain=plain_view,
        extra_hint=prep_hint,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
        on_chunk=_StageChunkLogger("core"),
        stream=True,
    )
    core_rules = core_result["content"]

    companion_result = await run_companion_stage(
        world_mode=world_mode,
        book_id=book_id,
        book_title=book_title,
        output_language=lang,
        book_markdown_plain=plain_view,
        extra_hint=prep_hint,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
        on_chunk=_StageChunkLogger("companion"),
        stream=True,
    )
    companion = {
        "filename": companion_result["filename"],
        "content": companion_result["content"],
        "world_mode": companion_result["world_mode"],
    }

    discovery_result = await run_discovery_stage(
        book_id=book_id,
        book_title=book_title,
        world_mode=world_mode,
        companion_file=companion.get("filename") or companion_filename_for_mode(world_mode),
        output_language=lang,
        current_core_rules_md=strip_core_retrieval_hooks(core_rules),
        current_companion_md=companion["content"],
        book_markdown_lined=prepared.discovery_lined_view or lined_view,
        extra_hint=prep_hint,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
        on_chunk=_StageChunkLogger("discovery"),
        stream=True,
    )
    discovery = apply_stage0_parameter_plan(
        discovery_result["manifest"],
        prepared=prepared,
    )

    packages = await run_packages(
        packages=(discovery.get("detailed_rule_packages") or []),
        book_id=book_id,
        book_title=book_title,
        output_language=lang,
        current_core_rules_md=strip_core_retrieval_hooks(core_rules),
        lined_view=lined_view,
        raw_lines=raw_lines,
        extra_hint=prep_hint,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
        on_chunk=_StageChunkLogger("package"),
        stream=True,
    )

    families = await run_families(
        families=(discovery.get("parameter_families") or []),
        book_id=book_id,
        book_title=book_title,
        output_language=lang,
        lined_view=prepared.parameter_lined_view or lined_view,
        raw_lines=prepared.parameter_raw_lines or raw_lines,
        extra_hint=prep_hint,
        model=stage_model,
        base_url=config.base_url,
        api_key=config.api_key,
        tracker=tracker,
        on_chunk=_StageChunkLogger("family"),
        stream=True,
    )

    character_sheet = await _run_character_sheet(
        discovery,
        book_id=book_id,
        book_title=book_title,
        output_language=lang,
        current_core_rules_md=strip_core_retrieval_hooks(core_rules),
        lined_view=lined_view,
        raw_lines=raw_lines,
        config=config,
        stage_model=stage_model,
        prep_hint=prep_hint,
        tracker=tracker,
    )

    final_manifest = assemble_final_manifest(
        discovery_manifest=discovery,
        produced_package_results=packages,
        produced_family_results=families,
        character_sheet_present=bool(
            (discovery.get("character_sheet_package") or {}).get("present"),
        ),
        character_sheet_failed=bool(character_sheet.get("error")),
    )
    core_rules, hook_stats = apply_core_retrieval_hooks(
        core_rules,
        manifest=final_manifest,
        produced_family_results=families,
        output_language=lang,
    )

    dice_ir = await _run_dice_ir(
        plain_view,
        book_title=book_title,
        output_language=lang,
        config=config,
        model=dice_model,
    )

    artifact: dict[str, Any] = {
        "version": 6,
        "book_id": book_id,
        "book_title": book_title,
        "world_mode": world_mode,
        "output_language": "zh" if lang == "Chinese" else "en",
        "language_precheck": precheck,
        "language_detected_at": _now_iso(),
        "model": stage_model,
        "requested_model": config.model,
        "parsed_at": _now_iso(),
        "files": [{"file_id": book_id, "filename": parsed.filename, "enabled": True}],
        "core_rules": core_rules,
        "companion": companion,
        "discovery_manifest": discovery,
        "rule_packages": packages,
        "parameter_families": families,
        "character_sheet": character_sheet,
        "final_manifest": final_manifest,
        "dice_ir": dice_ir or {},
        "token_usage": tracker.to_dict(),
        "stats": {
            "plain_chars": len(plain_view),
            "total_lines": len(raw_lines),
            "packages_count": len([p for p in packages if not p.get("error")]),
            "families_count": len([f for f in families if not f.get("error")]),
            "character_sheet_present": bool(character_sheet.get("template_json")),
            "source_format": parsed.source_format,
            "ocr_backend": parsed.backend,
            "ocr_pages": parsed.page_count,
            "images_dropped": parsed.images_dropped,
            "duration_seconds": parsed.duration_seconds,
            "workflow": "chatlab_rule_parser_v6",
            "source_compacted": prepared.compacted,
            "source_filtered": prepared.source_filtered,
            "source_chars_original": prepared.original_chars,
            "source_lines_original": prepared.original_lines,
            "working_source_chars": prepared.working_chars,
            "working_source_lines": prepared.working_lines,
            "working_source_chunks": prepared.chunk_count,
            "working_source_merge_passes": prepared.merge_passes,
            "discovery_source_chars": len(prepared.discovery_lined_view or ""),
            "source_dropped_chars": prepared.dropped_chars,
            "source_parameter_chars": prepared.parameter_chars,
            "source_dropped_sections": [
                {
                    "kind": s.kind,
                    "title": s.title,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "chars": s.chars,
                }
                for s in prepared.dropped_sections
            ],
            "source_parameter_sections": [
                {
                    "family_id": s.family_id,
                    "title": s.title,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "chars": s.chars,
                }
                for s in prepared.parameter_sections
            ],
            "core_hook_packages": hook_stats["packages"],
            "core_hook_families": hook_stats["families"],
        },
    }
    logger.info(
        "[ruleset-v6] complete book=%s packages=%d families=%d dice_ir=%s",
        book_title,
        artifact["stats"]["packages_count"],
        artifact["stats"]["families_count"],
        bool(artifact["dice_ir"]),
    )
    return artifact


async def _run_character_sheet(
    discovery: dict[str, Any],
    *,
    book_id: str,
    book_title: str,
    output_language: str,
    current_core_rules_md: str,
    lined_view: str,
    raw_lines: list[str],
    config: RulesetParseWorkflowConfig,
    stage_model: str,
    prep_hint: str | None,
    tracker: TokenTracker,
) -> dict[str, Any]:
    desc = discovery.get("character_sheet_package") or {}
    if not desc.get("present"):
        return {}
    descriptor = {
        "line_hints": desc.get("line_hints") or [],
        "source_cues": desc.get("source_cues") or [],
        "template_focus": desc.get("template_focus") or [],
        "guide_focus": desc.get("guide_focus") or [],
    }
    try:
        result = await run_character_sheet_stage(
            book_id=book_id,
            book_title=book_title,
            output_language=output_language,
            character_descriptor=descriptor,
            current_core_rules_md=current_core_rules_md,
            lined_view=lined_view,
            raw_lines=raw_lines,
            extra_hint=prep_hint,
            model=stage_model,
            base_url=config.base_url,
            api_key=config.api_key,
            tracker=tracker,
            on_chunk=_StageChunkLogger("character"),
            stream=True,
        )
    except Exception as exc:  # noqa: BLE001 - same resilience as ChatLab pipeline
        logger.warning("[ruleset-v6] character_sheet failed: %s", exc)
        return {"error": str(exc)}
    return {
        "template_filename": result["template_filename"],
        "template_content": result["template_content"],
        "template_json": result["template_json"],
        "guide_filename": result["guide_filename"],
        "guide_content": result["guide_content"],
    }


async def _run_dice_ir(
    markdown: str,
    *,
    book_title: str,
    output_language: str,
    config: RulesetParseWorkflowConfig,
    model: str,
) -> dict[str, Any] | None:
    dice_cfg = {
        "model": model,
        "base_url": config.dice_base_url or config.base_url,
        "api_key": config.dice_api_key or config.api_key,
    }
    if not dice_cfg.get("api_key"):
        return None
    try:
        return await run_dice_ir_stage(
            book_title=book_title,
            book_markdown_plain=markdown,
            output_language=output_language,
            file_ids=[],
            dice_ir_config=dice_cfg,
            previous_artifact={},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ruleset-v6] dice_ir failed: %s", exc)
        return {"error": str(exc)}


def _precheck(markdown: str, raw_lines: list[str]) -> dict[str, Any]:
    sample = markdown[:100_000]
    hanzi = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
    alpha = sum(1 for c in sample if c.isascii() and c.isalpha())
    language = "zh" if hanzi > alpha else "en"
    if language == "zh":
        tokens = len(markdown)
        label = "中文"
    else:
        tokens = max(1, len(markdown) // 3)
        label = "English"
    return {
        "language": language,
        "language_label": label,
        "total_tokens": tokens,
        "total_chars": len(markdown),
        "total_lines": len(raw_lines),
    }


def _model_for_source_size(model: str, source: str) -> str:
    """Use codex-relay's long-context model alias for full rulebooks."""
    cleaned = (model or "").strip()
    if not cleaned:
        return cleaned
    if cleaned.endswith("-all"):
        return cleaned
    if len(source) < 300_000:
        return cleaned
    if cleaned.startswith("gpt-5."):
        return f"{cleaned}-all"
    return cleaned


def _source_prep_hint(prepared: Any) -> str | None:
    sections = getattr(prepared, "parameter_sections", None) or []
    dropped = getattr(prepared, "dropped_sections", None) or []
    if not sections and not dropped:
        return None
    lines = [
        "Stage 0 source preparation has already removed bundled scenarios "
        "and split large catalog/table-like material out of the resident "
        "source. Treat the remaining source as the rules-first working "
        "rulebook.",
    ]
    if dropped:
        lines.append("")
        lines.append("Removed non-rule/scenario sections:")
        for section in dropped[:20]:
            lines.append(
                f"- {section.title}: original lines "
                f"{section.start_line}-{section.end_line}",
            )
    if sections:
        lines.append("")
        lines.append(
            "Parameter family candidates. Discovery should create "
            "parameter_families entries for these when mechanically useful, "
            "using the exact original line_hints shown here:",
        )
        for section in sections:
            lines.append(
                f"- {section.family_id}: {section.title}, "
                f"line_hints [[{section.start_line}, {section.end_line}]]",
            )
    return "\n".join(lines)


class _StageChunkLogger:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.chars_by_stage: dict[str, int] = {}
        self.next_log_by_stage: dict[str, int] = {}

    async def __call__(self, actual_stage: str, text: str) -> None:
        key = actual_stage or self.stage
        chars = self.chars_by_stage.get(key, 0) + len(text or "")
        self.chars_by_stage[key] = chars
        next_log_at = self.next_log_by_stage.get(key, 2_000)
        if chars >= next_log_at:
            logger.info(
                "[ruleset-v6] stream %s chars=%d",
                key,
                chars,
            )
            self.next_log_by_stage[key] = next_log_at + 2_000
