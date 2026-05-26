"""Stage 7 — Final manifest assembly (pure reducer, no LLM).

The discovery manifest already contains most of what the final
manifest needs. We just prune descriptors down to runtime fields,
confirm extant packages / families by the work actually produced in
stages 4-6, and emit the compact final manifest JSON string.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("chatlab.trpg")

FINAL_MANIFEST_FILE = "knowledge_manifest.json"

# Fields kept when compacting a detailed_rule_package descriptor.
_PACKAGE_KEEP = (
    "package_id", "title", "resident_presence", "summary",
    "load_when", "contains", "native_labels", "file",
)
_FAMILY_KEEP = (
    "family_id", "title", "summary", "entry_definition",
    "family_specific_fields", "native_labels", "file",
)


def _slim_package(src: Dict[str, Any]) -> Dict[str, Any]:
    return {k: src[k] for k in _PACKAGE_KEEP if k in src}


def _slim_family(src: Dict[str, Any]) -> Dict[str, Any]:
    return {k: src[k] for k in _FAMILY_KEEP if k in src}


def _index_by(key: str, items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(item.get(key)): item for item in items if item.get(key)}


def assemble_final_manifest(
    *,
    discovery_manifest: Dict[str, Any],
    produced_package_results: List[Dict[str, Any]],
    produced_family_results: List[Dict[str, Any]],
    character_sheet_present: bool,
    character_sheet_failed: bool = False,
) -> Dict[str, Any]:
    """Build the runtime knowledge_manifest.json.

    Keeps only packages / families that were actually produced without
    error. Preserves the resident section and conservative aliases.
    """
    pkg_index = _index_by("package_id", discovery_manifest.get("detailed_rule_packages") or [])
    fam_index = _index_by("family_id", discovery_manifest.get("parameter_families") or [])

    slim_packages: List[Dict[str, Any]] = []
    for result in produced_package_results:
        if result.get("error") or not result.get("content"):
            continue
        pkg_id = result.get("package_id")
        descriptor = pkg_index.get(str(pkg_id), {"package_id": pkg_id})
        slim = _slim_package(descriptor)
        slim["package_id"] = pkg_id
        slim.setdefault("file", result.get("filename") or f"rule_packages/{pkg_id}.md")
        slim_packages.append(slim)

    slim_families: List[Dict[str, Any]] = []
    for result in produced_family_results:
        if result.get("error"):
            continue
        if result.get("should_remain_markdown"):
            # Family was rejected for JSON extraction — drop from manifest.
            continue
        fam_id = result.get("family_id")
        descriptor = fam_index.get(str(fam_id), {"family_id": fam_id})
        slim = _slim_family(descriptor)
        slim["family_id"] = fam_id
        slim.setdefault("file", result.get("filename") or f"parameters/{fam_id}.json")
        if "family_specific_fields" not in slim:
            parsed = result.get("json") if isinstance(result.get("json"), dict) else {}
            schema = parsed.get("schema_used") if isinstance(parsed.get("schema_used"), dict) else {}
            fields = schema.get("family_specific_fields")
            if isinstance(fields, list):
                slim["family_specific_fields"] = fields
        slim_families.append(slim)

    resident = discovery_manifest.get("resident") or {}
    companion_file = resident.get("companion_file") or ""

    character_sheet: Dict[str, Any] = {
        "present": bool(character_sheet_present) and not character_sheet_failed,
        "template_file": "character_sheet/character_sheet_template.json",
        "guide_file": "character_sheet/character_creation_guide.md",
    }

    aliases_src = discovery_manifest.get("aliases") or []
    aliases = [
        {
            "alias": str(a.get("alias") or "").strip(),
            "target_type": str(a.get("target_type") or "").strip(),
            "target_id": str(a.get("target_id") or "").strip(),
        }
        for a in aliases_src
        if isinstance(a, dict) and a.get("alias") and a.get("target_id")
    ]

    manifest = {
        "book_id": discovery_manifest.get("book_id"),
        "book_title": discovery_manifest.get("book_title"),
        "world_mode": discovery_manifest.get("world_mode"),
        "resident": {
            "core_file": resident.get("core_file") or "core_rules.md",
            "companion_file": companion_file,
        },
        "detailed_rule_packages": slim_packages,
        "parameter_families": slim_families,
        "character_sheet_package": character_sheet,
        "aliases": aliases,
    }
    logger.info(
        "[V6-final] packages=%d families=%d character_sheet=%s aliases=%d",
        len(slim_packages), len(slim_families),
        character_sheet["present"], len(aliases),
    )
    return manifest


def manifest_to_json_string(manifest: Dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2)
