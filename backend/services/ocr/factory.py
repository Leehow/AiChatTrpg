"""Factory: pick the right backend from config."""

from __future__ import annotations

from typing import Any

from .. import ocr_config
from .base import OCRBackend, OCRError
from .mineru_cloud import MinerUCloudBackend, MinerUCloudOptions
from .mineru_local import MinerULocalBackend, MinerULocalOptions
from .pdftext_local import PDFTextLocalBackend, PDFTextLocalOptions

# Display labels for the UI provider picker. Ordered so the
# zero-install option leads — that's the right default for "I just
# pulled the repo".
PROVIDER_LABELS: dict[str, str] = {
    "pdftext_local": "PDF text (PyMuPDF, fast)",
    "mineru_local": "MinerU (local)",
    "mineru_cloud": "MinerU (cloud · mineru.net)",
}


def available_backends() -> list[dict[str, Any]]:
    """List of {name, label, available} for the UI dropdown."""
    out: list[dict[str, Any]] = []
    for name in ocr_config.PROVIDER_KEYS:
        cfg = ocr_config.get_resolved(name) or {}
        if name == "pdftext_local":
            available = bool(cfg.get("enabled", True))
        elif name == "mineru_local":
            available = bool(cfg.get("enabled", True))
        elif name == "mineru_cloud":
            available = bool(cfg.get("api_key"))
        else:
            available = False
        out.append(
            {
                "name": name,
                "label": PROVIDER_LABELS.get(name, name),
                "available": available,
            }
        )
    return out


def build_backend(provider: str) -> OCRBackend:
    cfg = ocr_config.get_resolved(provider)
    if cfg is None:
        raise OCRError(f"Unknown OCR provider '{provider}'")
    if provider == "pdftext_local":
        return PDFTextLocalBackend(PDFTextLocalOptions.from_dict(cfg))
    if provider == "mineru_local":
        return MinerULocalBackend(MinerULocalOptions.from_dict(cfg))
    if provider == "mineru_cloud":
        return MinerUCloudBackend(MinerUCloudOptions.from_dict(cfg))
    raise OCRError(f"No backend implementation for '{provider}'")
