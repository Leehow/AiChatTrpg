"""OCR provider configuration + smoke-test endpoints.

Single-user, single-config (mirrors how `admin_config` exposes LLM
providers). Two backends today: `mineru_local` (CLI) and
`mineru_cloud` (mineru.net REST). Adding a third (mistral, marker, …)
is "register the backend in services/ocr/factory.py + add an env
section in services/ocr_config.py".
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services import ocr_config
from services.ocr import OCRError, build_backend
from services.ocr.factory import PROVIDER_LABELS, available_backends

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OCRProviderInfo(BaseModel):
    provider: str
    label: str
    api_key_set: bool = False
    env_has_key: bool = False
    active: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class OCRProviderUpdate(BaseModel):
    """Partial update. Empty strings are ignored (preserve existing).
    The literal string `__clear__` resets the field to its env default.
    """

    api_key: str | None = None
    base_url: str | None = None
    cli: str | None = None
    backend: str | None = None
    lang: str | None = None
    model_version: str | None = None
    no_formula: bool | None = None
    no_table: bool | None = None
    enabled: bool | None = None


class OCRHealthResponse(BaseModel):
    provider: str
    ok: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class OCRTestResponse(BaseModel):
    provider: str
    ok: bool
    duration_seconds: float = 0.0
    page_count: int = 0
    markdown_preview: str = ""
    markdown_length: int = 0
    image_count: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/providers", response_model=list[OCRProviderInfo])
async def list_providers() -> list[OCRProviderInfo]:
    public = ocr_config.load_all_public()
    out: list[OCRProviderInfo] = []
    for name in ocr_config.PROVIDER_KEYS:
        cfg = public.get(name) or {}
        api_key_set = bool(cfg.pop("api_key_set", False))
        env_has_key = bool(cfg.pop("env_has_key", False))
        out.append(
            OCRProviderInfo(
                provider=name,
                label=PROVIDER_LABELS.get(name, name),
                api_key_set=api_key_set,
                env_has_key=env_has_key,
                active=bool(cfg.pop("active", False)),
                config=cfg,
            )
        )
    return out


@router.put("/providers/{provider}", response_model=OCRProviderInfo)
async def update_provider(provider: str, body: OCRProviderUpdate) -> OCRProviderInfo:
    if provider not in ocr_config.PROVIDER_KEYS:
        raise HTTPException(404, f"Unknown OCR provider '{provider}'")
    payload = body.model_dump(exclude_none=True)
    try:
        cfg = ocr_config.save_provider(provider, payload)
        ocr_config.set_active_provider(provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    api_key_set = bool(cfg.pop("api_key_set", False))
    env_has_key = bool(cfg.pop("env_has_key", False))
    cfg.pop("active", None)
    return OCRProviderInfo(
        provider=provider,
        label=PROVIDER_LABELS.get(provider, provider),
        api_key_set=api_key_set,
        env_has_key=env_has_key,
        active=True,
        config=cfg,
    )


@router.get("/providers/{provider}/health", response_model=OCRHealthResponse)
async def provider_health(provider: str) -> OCRHealthResponse:
    if provider not in ocr_config.PROVIDER_KEYS:
        raise HTTPException(404, f"Unknown OCR provider '{provider}'")
    try:
        backend = build_backend(provider)
    except OCRError as exc:
        return OCRHealthResponse(provider=provider, ok=False, detail={"error": str(exc)})
    detail = await backend.health()
    return OCRHealthResponse(
        provider=provider, ok=bool(detail.get("ok", False)), detail=detail
    )


@router.get("/available", response_model=list[dict[str, Any]])
async def list_available() -> list[dict[str, Any]]:
    """Lighter-weight listing for the picker — only what the dropdown needs."""
    return available_backends()


@router.post("/test", response_model=OCRTestResponse)
async def test_extract(
    provider: str = Form(...),
    file: UploadFile = File(...),
    preview_chars: int = Form(2000),
) -> OCRTestResponse:
    if provider not in ocr_config.PROVIDER_KEYS:
        raise HTTPException(400, f"Unknown OCR provider '{provider}'")
    if not file.filename:
        raise HTTPException(400, "filename required")

    suffix = Path(file.filename).suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(prefix="ocr-test-", suffix=suffix, delete=False)
    try:
        chunk = await file.read()
        tmp.write(chunk)
        tmp.flush()
        tmp.close()

        try:
            backend = build_backend(provider)
            result = await backend.extract(Path(tmp.name))
        except OCRError as exc:
            return OCRTestResponse(provider=provider, ok=False, error=str(exc))

        preview = result.markdown[: max(0, preview_chars)]
        return OCRTestResponse(
            provider=provider,
            ok=True,
            duration_seconds=result.duration_seconds,
            page_count=result.page_count,
            markdown_preview=preview,
            markdown_length=len(result.markdown),
            image_count=len(result.image_paths),
        )
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass
