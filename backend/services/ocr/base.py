"""Abstract OCR backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class OCRError(RuntimeError):
    """Raised when an OCR backend fails — wraps subprocess / HTTP errors
    so callers can show a single error type to the user."""


@dataclass
class OCRResult:
    """Normalised output from any OCR backend.

    `markdown` is the primary deliverable. `content_list` and `middle`
    are MinerU-specific extras the downstream semantic parser may want;
    they're optional so non-MinerU backends can leave them empty.
    """

    backend: str
    markdown: str
    page_count: int = 0
    duration_seconds: float = 0.0
    content_list: list[dict[str, Any]] = field(default_factory=list)
    middle: dict[str, Any] | None = None
    image_paths: list[str] = field(default_factory=list)
    raw_output_dir: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class OCRBackend(ABC):
    """One backend = one extraction strategy.

    Implementations must be re-entrant — a single instance may be reused
    across requests. They should NOT cache state between calls beyond
    cheap configuration.
    """

    name: str = "abstract"

    @abstractmethod
    async def extract(self, file_path: Path) -> OCRResult:
        """Run the backend against a single file. Should raise OCRError
        on any failure (do not return a partial OCRResult)."""

    async def health(self) -> dict[str, Any]:
        """Optional cheap probe — does the backend look usable right
        now? Default returns `{"ok": True}` so subclasses only override
        when they have something meaningful to check (e.g. CLI exists,
        cloud API key valid)."""
        return {"ok": True}
