"""OCR backends — turn PDFs (and other docs) into markdown.

Two backends today, both produce MinerU's standard output (markdown +
middle.json + content_list.json). The semantic step that turns this raw
markdown into a v6 ruleset/module JSON lives in chatlab and is not part
of this package.
"""

from .base import OCRBackend, OCRResult, OCRError
from .factory import build_backend, available_backends

__all__ = [
    "OCRBackend",
    "OCRResult",
    "OCRError",
    "build_backend",
    "available_backends",
]
