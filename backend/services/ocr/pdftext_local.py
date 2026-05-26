"""Lightweight PDF text extraction via PyMuPDF.

Zero-config alternative to MinerU — no external CLI, no GPU, no model
downloads. Pure Python wheel, ~20MB. Extracts text + uses the PDF's
own outline (bookmarks) to inject markdown headings so downstream TOC
extraction has something to chew on.

Trade-offs vs MinerU:
  + 100x faster (111-page module ≈ 2 seconds vs minutes)
  + Zero install friction
  + Works fully offline
  - Plain text only — no formula/table reconstruction (PyMuPDF gives
    table-as-text but loses cell structure)
  - Useless for image-only / scanned PDFs (no OCR)

So this is the right pick for "I have a normal text-based RPG module
PDF, just give me the words", and MinerU stays the right pick for
scanned books or layouts the simple extractor mangles.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import OCRBackend, OCRError, OCRResult

# Anything above this would be a chapter/section title in 99% of RPG
# books — running headers and footers are usually < 10pt.
_HEADING_FONT_SIZE_THRESHOLD = 13.0
_HEADING_RATIO_THRESHOLD = 1.25  # font size relative to body text median


@dataclass
class PDFTextLocalOptions:
    # Whether to inject markdown # headings derived from the PDF's
    # bookmark outline. Off → plain text only.
    use_outline_headings: bool = True
    # If the PDF has no outline, scan font sizes and synthesise headings
    # from anything visibly larger than body text.
    synthesise_headings_from_font_size: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PDFTextLocalOptions":
        return cls(
            use_outline_headings=bool(data.get("use_outline_headings", True)),
            synthesise_headings_from_font_size=bool(
                data.get("synthesise_headings_from_font_size", True)
            ),
        )


def _outline_to_anchors(toc: list[list[Any]]) -> dict[int, list[tuple[int, str]]]:
    """Convert PyMuPDF's outline into {page_index: [(level, title), ...]}.

    PyMuPDF returns toc as [[level, title, page1based], ...].
    """
    out: dict[int, list[tuple[int, str]]] = {}
    for entry in toc:
        if len(entry) < 3:
            continue
        try:
            level = int(entry[0])
            title = str(entry[1]).strip()
            page = int(entry[2]) - 1  # PyMuPDF returns 1-based
        except (TypeError, ValueError):
            continue
        if not title or page < 0:
            continue
        level = max(1, min(6, level))
        out.setdefault(page, []).append((level, title))
    return out


def _extract_with_outline(doc: Any) -> tuple[str, int, int]:
    """Fast path — concat each page's text, prefixing pages that match
    an outline entry with ``# Title`` lines.
    """
    headings_per_page = _outline_to_anchors(doc.get_toc(simple=True) or [])
    parts: list[str] = []
    heading_count = 0
    for i in range(len(doc)):
        page = doc.load_page(i)
        for level, title in headings_per_page.get(i, []):
            parts.append(f"\n\n{'#' * level} {title}\n")
            heading_count += 1
        text = page.get_text("text") or ""
        parts.append(text.strip())
    return "\n\n".join(p for p in parts if p), len(doc), heading_count


def _synthesise_headings(doc: Any) -> tuple[str, int, int]:
    """Fallback when the PDF has no outline — eyeball font sizes and
    promote anything visibly larger than body text to a heading.

    This is best-effort; for a clean text PDF it usually finds chapter
    titles, but a heavily styled book will produce some noise. Better
    than nothing for documents where the LLM would otherwise have to
    guess from raw text.
    """
    parts: list[str] = []
    heading_count = 0
    # First pass: estimate the body-text font size as the most common
    # span size across the doc.
    body_size = _estimate_body_size(doc)
    threshold = max(_HEADING_FONT_SIZE_THRESHOLD, body_size * _HEADING_RATIO_THRESHOLD)

    for i in range(len(doc)):
        page = doc.load_page(i)
        # `get_text("dict")` gives us per-span font info.
        info = page.get_text("dict") or {}
        for block in info.get("blocks", []):
            if block.get("type") != 0:  # 0 = text
                continue
            for line in block.get("lines", []):
                spans = line.get("spans") or []
                if not spans:
                    continue
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                max_size = max(float(s.get("size", 0) or 0) for s in spans)
                if max_size >= threshold and len(line_text) <= 80:
                    level = 1 if max_size >= body_size * 1.6 else 2
                    parts.append(f"\n\n{'#' * level} {line_text}\n")
                    heading_count += 1
                else:
                    parts.append(line_text)
    return "\n\n".join(parts), len(doc), heading_count


def _estimate_body_size(doc: Any) -> float:
    """Median font size across the first few pages. Cheap proxy for
    'body text' size."""
    sizes: list[float] = []
    for i in range(min(5, len(doc))):
        info = doc.load_page(i).get_text("dict") or {}
        for block in info.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans") or []:
                    s = float(span.get("size", 0) or 0)
                    if s > 0:
                        sizes.append(s)
    if not sizes:
        return 10.0
    sizes.sort()
    return sizes[len(sizes) // 2]


class PDFTextLocalBackend(OCRBackend):
    """Pure-Python PDF text backend backed by PyMuPDF."""

    name = "pdftext_local"

    def __init__(self, options: PDFTextLocalOptions):
        self.options = options

    async def health(self) -> dict[str, Any]:
        try:
            import fitz  # type: ignore
        except ImportError as exc:
            return {
                "ok": False,
                "error": f"pymupdf import failed: {exc}",
                "hint": "pip install pymupdf",
            }
        return {"ok": True, "version": getattr(fitz, "__version__", "unknown")}

    async def extract(self, file_path: Path) -> OCRResult:
        if not file_path.is_file():
            raise OCRError(f"Input file does not exist: {file_path}")
        # PyMuPDF is sync — defer to a thread so the event loop stays
        # responsive on bigger PDFs.
        return await asyncio.to_thread(self._extract_sync, file_path)

    def _extract_sync(self, file_path: Path) -> OCRResult:
        try:
            import fitz  # type: ignore
        except ImportError as exc:
            raise OCRError(f"pymupdf not installed: {exc}") from exc

        started = time.perf_counter()
        try:
            doc = fitz.open(str(file_path))
        except Exception as exc:
            raise OCRError(f"PyMuPDF could not open {file_path.name}: {exc}") from exc

        try:
            outline = doc.get_toc(simple=True) or []
            if outline and self.options.use_outline_headings:
                markdown, page_count, heading_count = _extract_with_outline(doc)
                strategy = "outline"
            elif self.options.synthesise_headings_from_font_size:
                markdown, page_count, heading_count = _synthesise_headings(doc)
                strategy = "font-size"
            else:
                parts = [doc.load_page(i).get_text("text") or "" for i in range(len(doc))]
                markdown = "\n\n".join(p.strip() for p in parts if p)
                page_count = len(doc)
                heading_count = 0
                strategy = "plain"
        finally:
            doc.close()

        duration = time.perf_counter() - started
        return OCRResult(
            backend=self.name,
            markdown=markdown,
            page_count=page_count,
            duration_seconds=round(duration, 3),
            content_list=[],
            middle=None,
            image_paths=[],
            raw_output_dir=None,
            extra={
                "strategy": strategy,
                "headings": heading_count,
                "outline_entries": len(outline),
                "images_dropped": 0,  # we never extract images in the first place
            },
        )
