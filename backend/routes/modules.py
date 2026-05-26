"""Module ingestion endpoint.

POST /api/modules/parse  — multipart upload (PDF / DOCX / PPTX / XLSX
/ MD / TXT). Returns the extracted markdown plus a TOC pulled out of
it via the model pool's default LLM (heuristic fallback if no model
is configured).

After text extraction, AiChatTrpg starts the shared semantic parser in the
background: structure, playable units, GM briefing, and appendix lookup
entries. Upload-time TOC is local/heuristic only; the semantic parser owns
the expensive LLM structure pass.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from orm.models import ParsedModule, User
from routes.deps import current_user, db_session
from services import module_semantic_jobs
from services import module_toc
from services.short_name import (
    extract_module_title,
    get_or_generate_module_title,
)
from services.module_parser import (
    OCR_EXTS,
    TEXT_EXTS,
    ModuleParseResult,
    parse_module,
    parse_module_streaming,
)
from services.ocr import OCRError
from services.ocr.mineru_local import ProgressEvent

router = APIRouter(prefix="/api/modules", tags=["modules"])

ACCEPTED_EXTS = sorted(OCR_EXTS | TEXT_EXTS)


class TOCEntryView(BaseModel):
    title: str
    level: int
    anchor: str = ""
    # 1-based inclusive line range in `markdown`; 0 means unknown
    # (LLM TOC entry that didn't map back to a heading line).
    line_start: int = 0
    line_end: int = 0


class ModuleParseResponse(BaseModel):
    """Returned from /parse and /parse-stream — the full parse plus the
    persisted row's id and owner so the UI can immediately reflect it
    in the saved-modules list without a follow-up GET."""

    id: str = ""
    owner_id: str = ""
    is_shared: bool = True
    filename: str
    source_format: Literal["pdf", "docx", "pptx", "xlsx", "image", "markdown", "text"]
    backend: str
    markdown: str
    page_count: int = 0
    images_dropped: int = 0
    duration_seconds: float = 0.0
    toc: list[TOCEntryView] = Field(default_factory=list)
    toc_source: Literal["llm", "heuristic"] = "heuristic"
    semantic_status: Literal["pending", "running", "done", "error"] = "pending"
    semantic_error: str = ""
    semantic_structure: dict[str, Any] = Field(default_factory=dict)
    semantic_steps: list[dict[str, Any]] = Field(default_factory=list)
    briefing_md: str = ""
    appendix_index: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ModuleSummary(BaseModel):
    """Lightweight list view — strips the full markdown and TOC."""

    id: str
    owner_id: str
    is_shared: bool
    filename: str
    source_format: str
    backend: str
    page_count: int
    chars: int
    toc_entries: int
    toc_source: str
    created_at: datetime
    updated_at: datetime


class ModuleShareRequest(BaseModel):
    is_shared: bool


def _summary(row: ParsedModule) -> ModuleSummary:
    return ModuleSummary(
        id=row.id,
        owner_id=row.owner_id,
        is_shared=bool(row.is_shared),
        filename=row.filename,
        source_format=row.source_format,
        backend=row.backend,
        page_count=row.page_count,
        chars=len(row.markdown or ""),
        toc_entries=len(row.toc or []),
        toc_source=row.toc_source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _full(row: ParsedModule) -> ModuleParseResponse:
    return ModuleParseResponse(
        id=row.id,
        owner_id=row.owner_id,
        is_shared=bool(row.is_shared),
        filename=row.filename,
        source_format=row.source_format,  # type: ignore[arg-type]
        backend=row.backend,
        markdown=row.markdown,
        page_count=row.page_count,
        images_dropped=row.images_dropped,
        duration_seconds=row.duration_seconds,
        toc=[
            TOCEntryView(
                title=str(e.get("title", "")),
                level=int(e.get("level", 1)),
                anchor=str(e.get("anchor", "")),
                line_start=int(e.get("line_start") or 0),
                line_end=int(e.get("line_end") or 0),
            )
            for e in (row.toc or [])
            if isinstance(e, dict)
        ],
        toc_source=row.toc_source or "heuristic",  # type: ignore[arg-type]
        semantic_status=row.semantic_status or "pending",  # type: ignore[arg-type]
        semantic_error=row.semantic_error or "",
        semantic_structure=row.semantic_structure or {},
        semantic_steps=row.semantic_steps or [],
        briefing_md=row.briefing_md or "",
        appendix_index=row.appendix_index or {},
        created_at=row.created_at,
    )


async def _persist_module(
    db: AsyncSession,
    owner_id: str,
    parsed: ModuleParseResult,
    toc_entries: list,
    toc_source: str,
) -> ParsedModule:
    row = ParsedModule(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        filename=parsed.filename,
        source_format=parsed.source_format,
        backend=parsed.backend,
        markdown=parsed.markdown,
        page_count=parsed.page_count,
        images_dropped=parsed.images_dropped,
        duration_seconds=parsed.duration_seconds,
        toc=[
            {
                "title": e.title,
                "level": e.level,
                "anchor": e.anchor,
                "line_start": e.line_start,
                "line_end": e.line_end,
            }
            for e in toc_entries
        ],
        toc_source=toc_source,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _start_semantic_parse(
    db: AsyncSession,
    row: ParsedModule,
) -> ParsedModule:
    row = await module_semantic_jobs.prepare_semantic_parse(db, row)
    module_semantic_jobs.enqueue_semantic_parse(row.id)
    return row


class ModuleTitleRequest(BaseModel):
    """Either pass `module_id` (preferred — title gets cached on the row)
    or `filename` + `markdown` for one-shot extraction without persistence.
    """
    module_id: str | None = None
    filename: str | None = None
    markdown: str = ""


class ModuleTitleResponse(BaseModel):
    title: str
    cached: bool = False


@router.post("/extract-title", response_model=ModuleTitleResponse)
async def extract_title(
    body: ModuleTitleRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ModuleTitleResponse:
    """Clean module title for the room name `[coc]<title>`.

    Two modes:
      - `module_id` set → look up the row, return cached title if present,
        otherwise call the fast model and cache the result.
      - `filename`+`markdown` only → one-shot extraction, no persistence
        (used by older flows without a saved module).

    Falls back to a tidied filename when the model is unavailable.
    """
    if body.module_id:
        row = await db.get(ParsedModule, body.module_id)
        if row is None or not _can_see(row, user.id):
            raise HTTPException(404, "module not found")
        cached = bool(row.extracted_title)
        title = await get_or_generate_module_title(db, row)
        return ModuleTitleResponse(title=title, cached=cached)
    if not body.filename:
        raise HTTPException(422, "module_id or filename is required")
    title = await extract_module_title(db, body.filename, body.markdown)
    return ModuleTitleResponse(title=title, cached=False)


@router.post("/parse", response_model=ModuleParseResponse)
async def parse_uploaded_module(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ModuleParseResponse:
    if not file.filename:
        raise HTTPException(400, "filename required")
    ext = Path(file.filename).suffix.lower()
    if ext not in ACCEPTED_EXTS:
        raise HTTPException(
            400,
            f"Unsupported extension '{ext}'. Allowed: {', '.join(ACCEPTED_EXTS)}",
        )

    suffix = ext or ".bin"
    tmp = tempfile.NamedTemporaryFile(prefix="module-", suffix=suffix, delete=False)
    try:
        chunk = await file.read()
        tmp.write(chunk)
        tmp.flush()
        tmp.close()

        try:
            parsed = await parse_module(Path(tmp.name), file.filename)
        except OCRError as exc:
            raise HTTPException(500, str(exc)) from exc

        toc_entries = module_toc.annotate_with_lines(
            parsed.markdown, module_toc.heuristic_toc(parsed.markdown)
        )
        toc_source: Literal["llm", "heuristic"] = "heuristic"
        row = await _persist_module(db, user.id, parsed, toc_entries, toc_source)
        row = await _start_semantic_parse(db, row)
        return _full(row)
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass


@router.get("/accepted-extensions", response_model=list[str])
async def accepted_extensions() -> list[str]:
    return ACCEPTED_EXTS


# ---------------------------------------------------------------------------
# Library — list / read / delete persisted modules. List + read are open
# to any signed-in user (the library is shared); delete requires owner.
# ---------------------------------------------------------------------------


def _can_see(row: ParsedModule, user_id: str) -> bool:
    return bool(row.is_shared) or row.owner_id == user_id


@router.get("", response_model=list[ModuleSummary])
async def list_modules(
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> list[ModuleSummary]:
    """Visible modules = mine ∪ everyone-else's-shared, ordered by recency."""
    res = await db.execute(
        select(ParsedModule).where(
            (ParsedModule.owner_id == user.id) | (ParsedModule.is_shared == True)  # noqa: E712
        ).order_by(ParsedModule.created_at.desc())
    )
    return [_summary(r) for r in res.scalars()]


@router.get("/{module_id}", response_model=ModuleParseResponse)
async def get_module(
    module_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ModuleParseResponse:
    row = await db.get(ParsedModule, module_id)
    if row is None or not _can_see(row, user.id):
        # Mask private modules as 404 rather than 403 — leaks less about
        # whether a given id exists at all.
        raise HTTPException(404, "module not found")
    return _full(row)


@router.post("/{module_id}/semantic/parse", response_model=ModuleParseResponse)
async def parse_module_semantic(
    module_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ModuleParseResponse:
    row = await db.get(ParsedModule, module_id)
    if row is None or not _can_see(row, user.id):
        raise HTTPException(404, "module not found")
    if row.owner_id != user.id:
        raise HTTPException(403, "only the owner can reparse this module")
    row = await _start_semantic_parse(db, row)
    return _full(row)


@router.delete("/{module_id}")
async def delete_module(
    module_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> Response:
    row = await db.get(ParsedModule, module_id)
    if row is None or not _can_see(row, user.id):
        raise HTTPException(404, "module not found")
    if row.owner_id != user.id:
        raise HTTPException(403, "only the owner can delete this module")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("/{module_id}/share", response_model=ModuleSummary)
async def set_module_shared(
    module_id: str,
    body: ModuleShareRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ModuleSummary:
    """Toggle visibility. Only the owner can flip the flag."""
    row = await db.get(ParsedModule, module_id)
    if row is None or not _can_see(row, user.id):
        raise HTTPException(404, "module not found")
    if row.owner_id != user.id:
        raise HTTPException(403, "only the owner can change visibility")
    row.is_shared = bool(body.is_shared)
    await db.commit()
    await db.refresh(row)
    return _summary(row)


# ---------------------------------------------------------------------------
# Streaming variant — same payload and result, but emits SSE progress
# events as MinerU writes log lines so the UI can show a live status.
# Event protocol:
#   data: {"type": "log", "line": "..."}                  ← any stderr line
#   data: {"type": "progress", "page": N, "total": M}     ← parsed page X/Y
#   data: {"type": "done", "result": {...same shape...}}  ← terminal success
#   data: {"type": "error", "message": "..."}             ← terminal failure
# ---------------------------------------------------------------------------


@router.post("/parse-stream")
async def parse_uploaded_module_stream(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> EventSourceResponse:
    if not file.filename:
        raise HTTPException(400, "filename required")
    ext = Path(file.filename).suffix.lower()
    if ext not in ACCEPTED_EXTS:
        raise HTTPException(
            400,
            f"Unsupported extension '{ext}'. Allowed: {', '.join(ACCEPTED_EXTS)}",
        )

    # Buffer the upload now so we don't keep the multipart stream open
    # for the duration of the parse.
    chunk = await file.read()
    suffix = ext or ".bin"
    tmp = tempfile.NamedTemporaryFile(prefix="module-", suffix=suffix, delete=False)
    tmp.write(chunk)
    tmp.flush()
    tmp.close()
    upload_path = Path(tmp.name)
    original_name = file.filename

    async def event_stream():
        try:
            parsed_result: ModuleParseResult | None = None
            async for item in parse_module_streaming(upload_path, original_name):
                if isinstance(item, ProgressEvent):
                    if item.kind == "progress":
                        yield {
                            "data": json.dumps(
                                {
                                    "type": "progress",
                                    "page": item.page,
                                    "total": item.total,
                                    "line": item.line,
                                }
                            )
                        }
                    else:
                        yield {
                            "data": json.dumps(
                                {"type": "log", "line": item.line}
                            )
                        }
                else:
                    parsed_result = item

            if parsed_result is None:
                yield {
                    "data": json.dumps(
                        {"type": "error", "message": "no result produced"}
                    )
                }
                return

            # Upload-time TOC is intentionally local and fast. The shared
            # semantic parser does the expensive LLM structure pass once in
            # the background, so we do not spend another LLM call here.
            yield {
                "data": json.dumps(
                    {
                        "type": "stage",
                        "stage": "toc",
                        "ocr_pages": parsed_result.page_count,
                        "ocr_chars": len(parsed_result.markdown),
                    }
                )
            }

            toc_entries = module_toc.annotate_with_lines(
                parsed_result.markdown,
                module_toc.heuristic_toc(parsed_result.markdown),
            )
            toc_source = "heuristic"

            row = await _persist_module(
                db, user.id, parsed_result, toc_entries, toc_source
            )
            yield {
                "data": json.dumps(
                    {
                        "type": "stage",
                        "stage": "semantic",
                        "toc_entries": len(toc_entries),
                        "ocr_chars": len(parsed_result.markdown),
                    },
                    ensure_ascii=False,
                )
            }
            row = await _start_semantic_parse(db, row)
            payload = _full(row)
            yield {
                "data": json.dumps(
                    {"type": "done", "result": payload.model_dump(mode="json")},
                    ensure_ascii=False,
                )
            }
        except OCRError as exc:
            yield {"data": json.dumps({"type": "error", "message": str(exc)})}
        except Exception as exc:  # pragma: no cover — defensive
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                )
            }
        finally:
            try:
                upload_path.unlink(missing_ok=True)
            except OSError:
                pass

    return EventSourceResponse(event_stream())
