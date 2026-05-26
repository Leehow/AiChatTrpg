"""Ruleset file ingestion: PDF / Markdown / text -> v6-compatible artifact."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .module_parser import ModuleParseResult, parse_module
from .ocr import OCRError
from .ruleset_parse_workflow import (
    RulesetParseWorkflowConfig,
    run_ruleset_parse_workflow,
)

RULESET_FILE_EXTS = {".pdf", ".md", ".markdown", ".txt"}


def accepted_ruleset_file_extensions() -> list[str]:
    return sorted(RULESET_FILE_EXTS)


async def parse_ruleset_file(
    file_path: Path,
    original_name: str,
    *,
    output_language: str | None = None,
    workflow_config: RulesetParseWorkflowConfig | None = None,
) -> dict[str, Any]:
    """Parse an uploaded ruleset file into the v6 JSON shape the app stores.

    PDF extraction intentionally reuses ``module_parser.parse_module`` so the
    same operator-selected OCR/PDF backend is used for rules and modules.
    Once every format is normalized to markdown, the ruleset workflow compiles
    that markdown into the same JSON artifact shape accepted by direct v6 JSON
    uploads.
    """
    ext = Path(original_name).suffix.lower()
    if ext not in RULESET_FILE_EXTS:
        raise OCRError(
            f"Unsupported extension '{ext}'. Allowed: "
            f"{', '.join(accepted_ruleset_file_extensions())}"
        )

    parsed = await parse_module(file_path, original_name)
    markdown = (parsed.markdown or "").strip()
    if not markdown:
        raise OCRError("No text could be extracted from this ruleset file")

    if workflow_config is not None:
        return await run_ruleset_parse_workflow(
            parsed,
            output_language=_normalise_language(output_language),
            config=workflow_config,
        )

    return build_ruleset_artifact(
        parsed,
        output_language=_normalise_language(output_language),
    )


def build_ruleset_artifact(
    parsed: ModuleParseResult,
    *,
    output_language: str | None = None,
) -> dict[str, Any]:
    title = _title_from_filename(parsed.filename)
    book_id = f"{_slug(title) or 'ruleset'}-{uuid.uuid4().hex[:8]}"
    artifact: dict[str, Any] = {
        "version": 6,
        "book_id": book_id,
        "book_title": title,
        "world_mode": "fiction",
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "file_id": book_id,
                "filename": parsed.filename,
                "enabled": True,
            }
        ],
        "core_rules": parsed.markdown,
        "rule_packages": [],
        "parameter_families": [],
        "stats": {
            "plain_chars": len(parsed.markdown),
            "total_lines": parsed.markdown.count("\n") + 1,
            "packages_count": 0,
            "families_count": 0,
            "character_sheet_present": False,
            "source_format": parsed.source_format,
            "ocr_backend": parsed.backend,
            "ocr_pages": parsed.page_count,
            "images_dropped": parsed.images_dropped,
            "duration_seconds": parsed.duration_seconds,
        },
    }
    if output_language:
        artifact["output_language"] = output_language
    return artifact


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Untitled Ruleset"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:48].strip("-")


def _normalise_language(value: str | None) -> str | None:
    lang = (value or "").strip().lower()
    if lang in {"zh", "zh-cn", "chinese"}:
        return "zh"
    if lang in {"en", "en-us", "english"}:
        return "en"
    return None
