"""Pure helpers for the v6 ruleset pipeline.

These were inlined in `pipeline.py`. They are stateless and contain no
LLM I/O, so they live here so `pipeline.py` can stay focused on the
stream orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .stages.companion import companion_filename_for_mode


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_artifact_seed(
    *,
    book_id: str,
    book_title: str,
    world_mode: str,
    output_language: Optional[str],
    model: str,
    existing: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the artifact dict we'll mutate + persist across stages."""
    seed = dict(existing or {})
    seed["version"] = 6
    seed["book_id"] = book_id
    seed["book_title"] = book_title
    seed["world_mode"] = world_mode
    seed["output_language"] = output_language or "auto"
    seed["model"] = model
    seed.setdefault("core_rules", existing.get("core_rules") or "")
    seed.setdefault("companion", existing.get("companion") or {
        "filename": companion_filename_for_mode(world_mode),
        "content": "",
        "world_mode": world_mode,
    })
    seed.setdefault("discovery_manifest", existing.get("discovery_manifest") or {})
    seed.setdefault("rule_packages", existing.get("rule_packages") or [])
    seed.setdefault("parameter_families", existing.get("parameter_families") or [])
    seed.setdefault("character_sheet", existing.get("character_sheet") or {})
    seed.setdefault("final_manifest", existing.get("final_manifest") or {})
    seed.setdefault("dice_ir", existing.get("dice_ir") or {})
    seed.setdefault("history", existing.get("history") or [])
    return seed


def upsert(items: List[Dict[str, Any]], key: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Replace the matching item by id key, or append if new."""
    out = [dict(x) for x in items]
    target_id = result.get(key)
    for idx, item in enumerate(out):
        if item.get(key) == target_id:
            out[idx] = result
            return out
    out.append(result)
    return out


def find_descriptor(
    descriptors: List[Dict[str, Any]], key: str, slug: str,
) -> Optional[Dict[str, Any]]:
    for d in descriptors:
        if str(d.get(key) or "").strip() == slug:
            return d
    return None


def character_descriptor(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the character sheet descriptor from the manifest."""
    cs = manifest.get("character_sheet_package") or {}
    return {
        "line_hints": cs.get("line_hints") or [],
        "source_cues": cs.get("source_cues") or [],
        "template_focus": cs.get("template_focus") or [],
        "guide_focus": cs.get("guide_focus") or [],
    }
