"""Module ingestion: file → markdown.

Routes uploaded files to the right extractor:

  PDF / DOCX / PPTX / XLSX / image  → MinerU OCR backend (per ocr_config)
  Markdown / plain text            → read directly

The OCR backend strips images post-parse (see result_parser.drop_images).
We keep formulas and tables — they're useful for rule modules.

This is the open-source ingestion layer. Turning markdown into
structured v6 module JSON (scenes, NPCs, encounters, etc.) is still
chatlab-only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Union

from .ocr import OCRError, build_backend
from .ocr.mineru_local import MinerULocalBackend, ProgressEvent
from .ocr.result_parser import strip_images_from_markdown
from .ocr_config import get_active_provider, get_resolved

OCR_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".png", ".jpg", ".jpeg"}
TEXT_EXTS = {".md", ".markdown", ".txt"}

SourceFormat = Literal["pdf", "docx", "pptx", "xlsx", "image", "markdown", "text"]


@dataclass
class ModuleParseResult:
    filename: str
    source_format: SourceFormat
    markdown: str
    page_count: int = 0
    images_dropped: int = 0
    duration_seconds: float = 0.0
    backend: str = ""


def _ocr_provider(file_format: str) -> str:
    """Pick the OCR provider for a given file format.

    Selection logic:
      - For PDFs, the operator-selected provider from OCR settings wins
        when that provider is currently usable.
      - Cloud wins if the operator has set a mineru.net API key.
      - For text-based PDFs the lightweight pdftext_local is the right
        default — zero install, ~100x faster, and good enough quality
        when the source has selectable text. Bookmark-based heading
        recovery means we still get a usable TOC.
      - For DOCX / PPTX / XLSX / images, only MinerU can handle them,
        so we route to mineru_local even if pdftext is "available".
      - Anything else: mineru_local as last resort.
    """
    if file_format == "pdf":
        active = get_active_provider()
        if _provider_available(active):
            return active

    cloud = get_resolved("mineru_cloud") or {}
    if cloud.get("api_key"):
        return "mineru_cloud"
    if file_format == "pdf":
        pdftext = get_resolved("pdftext_local") or {}
        if pdftext.get("enabled", True):
            return "pdftext_local"
    return "mineru_local"


def _provider_available(provider: str) -> bool:
    cfg = get_resolved(provider) or {}
    if provider == "pdftext_local":
        return bool(cfg.get("enabled", True))
    if provider == "mineru_local":
        return bool(cfg.get("enabled", True))
    if provider == "mineru_cloud":
        return bool(cfg.get("api_key"))
    return False


def _detect_format(path: Path) -> SourceFormat:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".doc"):
        return "docx"
    if ext == ".pptx":
        return "pptx"
    if ext == ".xlsx":
        return "xlsx"
    if ext in (".png", ".jpg", ".jpeg"):
        return "image"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext == ".txt":
        return "text"
    raise OCRError(f"Unsupported file extension '{ext}'")


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


async def parse_module(file_path: Path, original_name: str) -> ModuleParseResult:
    """Single entrypoint: turn an uploaded file into a ModuleParseResult."""
    if not file_path.is_file():
        raise OCRError(f"Input file does not exist: {file_path}")
    fmt = _detect_format(Path(original_name))

    if fmt in ("markdown", "text"):
        raw = _read_text_file(file_path)
        # Strip image refs to match OCR-path behaviour: chatrpg modules
        # are text-only.
        markdown, dropped = strip_images_from_markdown(raw)
        return ModuleParseResult(
            filename=original_name,
            source_format=fmt,
            markdown=markdown,
            page_count=markdown.count("\n\n") + 1,
            images_dropped=dropped,
            backend="passthrough",
        )

    if fmt not in {f for f in ("pdf", "docx", "pptx", "xlsx", "image")}:
        raise OCRError(f"Unsupported format '{fmt}'")

    provider = _ocr_provider(fmt)
    backend = build_backend(provider)
    result = await backend.extract(file_path)

    return ModuleParseResult(
        filename=original_name,
        source_format=fmt,
        markdown=result.markdown,
        page_count=result.page_count,
        images_dropped=int(result.extra.get("images_dropped", 0))
        if isinstance(result.extra, dict)
        else 0,
        duration_seconds=result.duration_seconds,
        backend=provider,
    )


StreamItem = Union[ProgressEvent, ModuleParseResult]


async def parse_module_streaming(
    file_path: Path, original_name: str
) -> AsyncIterator[StreamItem]:
    """Streaming variant — yields ProgressEvent for each MinerU log
    line, then a single ModuleParseResult at the end.

    For passthrough formats (md/txt) and cloud backend there's nothing
    to stream, so we just emit one synthetic 'log' event then the
    result. Local MinerU is the path that benefits from real-time
    output."""
    if not file_path.is_file():
        raise OCRError(f"Input file does not exist: {file_path}")
    fmt = _detect_format(Path(original_name))

    if fmt in ("markdown", "text"):
        raw = _read_text_file(file_path)
        markdown, dropped = strip_images_from_markdown(raw)
        yield ProgressEvent(kind="log", line=f"Reading {fmt} passthrough...")
        yield ModuleParseResult(
            filename=original_name,
            source_format=fmt,
            markdown=markdown,
            page_count=markdown.count("\n\n") + 1,
            images_dropped=dropped,
            backend="passthrough",
        )
        return

    if fmt not in {f for f in ("pdf", "docx", "pptx", "xlsx", "image")}:
        raise OCRError(f"Unsupported format '{fmt}'")

    provider = _ocr_provider(fmt)
    backend = build_backend(provider)

    if not isinstance(backend, MinerULocalBackend):
        # Cloud or future backends — no native streaming, fall back to
        # one synthetic "started" event then the eventual result.
        yield ProgressEvent(
            kind="log", line=f"Submitting to {provider} (no streaming progress)"
        )
        result = await backend.extract(file_path)
        yield ModuleParseResult(
            filename=original_name,
            source_format=fmt,
            markdown=result.markdown,
            page_count=result.page_count,
            images_dropped=int(result.extra.get("images_dropped", 0))
            if isinstance(result.extra, dict)
            else 0,
            duration_seconds=result.duration_seconds,
            backend=provider,
        )
        return

    final_result = None
    async for event in backend.extract_streaming(file_path):
        if isinstance(event, ProgressEvent):
            yield event
        else:
            final_result = event
    if final_result is None:
        raise OCRError("MinerU stream finished without producing a result")

    yield ModuleParseResult(
        filename=original_name,
        source_format=fmt,
        markdown=final_result.markdown,
        page_count=final_result.page_count,
        images_dropped=int(final_result.extra.get("images_dropped", 0))
        if isinstance(final_result.extra, dict)
        else 0,
        duration_seconds=final_result.duration_seconds,
        backend=provider,
    )
