"""Parse MinerU output directories / zips into OCRResult.

MinerU writes a folder structure like:

    <out>/<filename>/auto/
        <filename>.md            ← primary markdown
        <filename>_content_list.json
        <filename>_middle.json
        <filename>_origin.pdf    (optional copy of input)
        images/*.jpg

Both the local CLI and the cloud API ZIP follow this layout, so the
same parser handles both.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

# Markdown image syntax: ![alt](path "title"). MinerU emits
# `![](images/<hash>.jpg)`. We drop the whole line because chatrpg
# stores text-only modules — images would need OSS hosting we don't
# have on the open-source side. Tables (HTML <table>...) and formulas
# ($...$ / $$...$$) are kept untouched.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def find_artifact_dir(base: Path) -> Path:
    """Walk into the MinerU output until we find the dir containing the
    .md file. Tolerates the various nesting MinerU has used over
    versions: <base>/<stem>/auto/, <base>/auto/, or <base>/."""
    if (base / "auto").is_dir():
        return base / "auto"
    # Single subdirectory that itself contains auto/
    subs = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    for sub in subs:
        if (sub / "auto").is_dir():
            return sub / "auto"
        if any(p.suffix == ".md" for p in sub.iterdir() if p.is_file()):
            return sub
    if any(p.suffix == ".md" for p in base.iterdir() if p.is_file()):
        return base
    # Last resort: deepest dir with a .md
    for p in base.rglob("*.md"):
        return p.parent
    raise FileNotFoundError(f"No markdown file found under {base}")


def _read_json_if(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def strip_images_from_markdown(markdown: str) -> tuple[str, int]:
    """Remove image references from markdown. Returns (clean, count)."""
    matches = _MD_IMAGE_RE.findall(markdown)
    if not matches:
        return markdown, 0
    cleaned = _MD_IMAGE_RE.sub("", markdown)
    # Collapse the blank lines that MinerU leaves where images used to be.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, len(matches)


def parse_artifact_dir(
    artifact_dir: Path, *, drop_images: bool = True
) -> dict[str, Any]:
    """Extract the bits we care about from a MinerU output folder.

    Returns a dict matching OCRResult fields (caller wraps in dataclass).
    Markdown is required; everything else is best-effort. With
    `drop_images=True` (default) markdown image refs are stripped — the
    extras dict reports how many were dropped.
    """
    md_files = sorted(artifact_dir.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md in {artifact_dir}")
    markdown = md_files[0].read_text(encoding="utf-8", errors="replace")
    images_dropped = 0
    if drop_images:
        markdown, images_dropped = strip_images_from_markdown(markdown)

    content_list: list[dict[str, Any]] = []
    middle: dict[str, Any] | None = None

    for json_path in artifact_dir.glob("*.json"):
        name = json_path.name
        if name.endswith("_content_list.json") or name == "content_list.json":
            data = _read_json_if(json_path)
            if isinstance(data, list):
                content_list = data
        elif name.endswith("_middle.json") or name == "middle.json":
            data = _read_json_if(json_path)
            if isinstance(data, dict):
                middle = data

    images_dir = artifact_dir / "images"
    image_paths: list[str] = []
    if images_dir.is_dir():
        image_paths = sorted(
            str(p.relative_to(artifact_dir)) for p in images_dir.iterdir() if p.is_file()
        )

    page_count = 0
    if isinstance(middle, dict):
        pages = middle.get("pdf_info") or middle.get("pages") or []
        if isinstance(pages, list):
            page_count = len(pages)

    return {
        "markdown": markdown,
        "page_count": page_count,
        "content_list": content_list,
        "middle": middle,
        "image_paths": image_paths,
        "raw_output_dir": str(artifact_dir),
        "images_dropped": images_dropped,
    }


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Unzip a MinerU result archive and return the artifact dir."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    return find_artifact_dir(dest)
