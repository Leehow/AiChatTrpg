"""v6 zip export — materialize the DB artifact into the v2.0 directory layout.

Emits an in-memory zip with this tree:

  core_rules.md
  world_guide.md OR style_guide.md
  knowledge_manifest.json
  rule_packages/{package_id}.md ...
  parameters/{family_id}.json ...
  character_sheet/character_sheet_template.json
  character_sheet/character_creation_guide.md

Packages / families with stage errors are skipped. The final manifest
is rebuilt from the current DB state at export time so the archive
always matches what's in the zip.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any, Dict, Tuple

from .stages.final_manifest import assemble_final_manifest

logger = logging.getLogger("chatlab.trpg")


def _safe_filename(raw: Any, fallback: str) -> str:
    """Coerce LLM-supplied filenames to safe relative paths.

    Strips path traversal (.. / leading /), collapses backslashes, and
    falls back to a synthetic name when the input is blank.
    """
    text = str(raw or "").strip()
    if not text:
        return fallback
    text = text.replace("\\", "/").lstrip("/")
    cleaned = "/".join(
        seg for seg in text.split("/") if seg and seg not in ("..", ".")
    )
    return cleaned or fallback


def _add_if_content(
    zf: zipfile.ZipFile, path: str, content: Any,
) -> bool:
    text = str(content or "")
    if not text.strip():
        return False
    zf.writestr(path, text)
    return True


def build_v6_zip(artifact: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    """Build a v6 zip in v2.0 directory layout.

    Returns (zip_bytes, summary). summary lists the files actually
    written, so the route can include them in the response headers or
    JSON body if desired.
    """
    buf = io.BytesIO()
    written: Dict[str, int] = {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        core = artifact.get("core_rules") or ""
        if _add_if_content(zf, "core_rules.md", core):
            written["core_rules.md"] = len(str(core))

        companion = artifact.get("companion") or {}
        companion_filename = _safe_filename(
            companion.get("filename"), "world_guide.md",
        )
        if _add_if_content(
            zf, companion_filename, companion.get("content"),
        ):
            written[companion_filename] = len(str(companion.get("content") or ""))

        # Rule packages — skip failed extractions.
        for pkg in artifact.get("rule_packages") or []:
            if pkg.get("error") or not pkg.get("content"):
                continue
            pkg_id = str(pkg.get("package_id") or "").strip()
            filename = _safe_filename(
                pkg.get("filename"),
                f"rule_packages/{pkg_id or 'unknown'}.md",
            )
            if _add_if_content(zf, filename, pkg.get("content")):
                written[filename] = len(str(pkg.get("content") or ""))

        # Parameter families — emit JSON for any successfully parsed
        # family, even if should_remain_markdown is true (the JSON
        # wrapper carries that flag for downstream consumers).
        for fam in artifact.get("parameter_families") or []:
            if fam.get("error"):
                continue
            content = fam.get("content") or ""
            if not content and fam.get("json") is not None:
                content = json.dumps(
                    fam.get("json"), ensure_ascii=False, indent=2,
                )
            if not content:
                continue
            fam_id = str(fam.get("family_id") or "").strip()
            filename = _safe_filename(
                fam.get("filename"),
                f"parameters/{fam_id or 'unknown'}.json",
            )
            if _add_if_content(zf, filename, content):
                written[filename] = len(str(content))

        # Character sheet package (may be absent or error).
        cs = artifact.get("character_sheet") or {}
        if not cs.get("error"):
            tpl_name = _safe_filename(
                cs.get("template_filename"),
                "character_sheet/character_sheet_template.json",
            )
            if _add_if_content(zf, tpl_name, cs.get("template_content")):
                written[tpl_name] = len(str(cs.get("template_content") or ""))
            guide_name = _safe_filename(
                cs.get("guide_filename"),
                "character_sheet/character_creation_guide.md",
            )
            if _add_if_content(zf, guide_name, cs.get("guide_content")):
                written[guide_name] = len(str(cs.get("guide_content") or ""))

        # Final manifest — rebuild from current state so export is always
        # consistent with the files actually emitted above.
        manifest = assemble_final_manifest(
            discovery_manifest=artifact.get("discovery_manifest") or {},
            produced_package_results=artifact.get("rule_packages") or [],
            produced_family_results=artifact.get("parameter_families") or [],
            character_sheet_present=bool(cs.get("template_content")),
            character_sheet_failed=bool(cs.get("error")),
        )
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        zf.writestr("knowledge_manifest.json", manifest_text)
        written["knowledge_manifest.json"] = len(manifest_text)

        # Stage 8 dice IR — emit the full artifact so an importer can
        # restore the compiled check_specs without re-running the LLM.
        dice_ir = artifact.get("dice_ir") or {}
        if isinstance(dice_ir, dict) and dice_ir.get("package"):
            dice_ir_text = json.dumps(dice_ir, ensure_ascii=False, indent=2)
            zf.writestr("dice_ir.json", dice_ir_text)
            written["dice_ir.json"] = len(dice_ir_text)

    zip_bytes = buf.getvalue()
    summary = {
        "files": written,
        "file_count": len(written),
        "total_bytes": sum(written.values()),
        "zip_bytes": len(zip_bytes),
    }
    logger.info(
        "[V6-export] files=%d zip_bytes=%d", len(written), len(zip_bytes),
    )
    return zip_bytes, summary


def suggested_zip_filename(artifact: Dict[str, Any]) -> str:
    """Pick a reasonable download filename based on book metadata."""
    book_id = str(artifact.get("book_id") or "").strip() or "ruleset"
    safe = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in book_id
    )
    return f"{safe}_v6.zip"
