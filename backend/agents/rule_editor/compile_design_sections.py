"""Rule-package and parameter-family builders for the design-state compiler.

Engine-pure: no FastAPI / ORM / React imports. Same input -> same output.
Owned by the compiler facade; nothing else should import from here.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .compile_design_markdown import CATALOG_NAMES


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]+$")


# ---------------------------------------------------------------------------
# Rule packages -- one per authored procedure
# ---------------------------------------------------------------------------


def build_rule_packages(state: dict[str, Any]) -> list[dict[str, Any]]:
    procedures = state.get("procedures") or []
    if not isinstance(procedures, list):
        return []
    packages: list[dict[str, Any]] = []
    for proc in procedures:
        if not isinstance(proc, dict):
            continue
        pid = str(proc.get("id") or "").strip()
        if not pid or not _SAFE_ID.match(pid):
            continue
        # Procedure payloads are flat: the reducer mixes `id` into the
        # entry alongside the authored fields (name, summary, steps...).
        body = {k: v for k, v in proc.items() if k != "id"}
        packages.append({
            "package_id": pid,
            "filename": f"procedures/{pid}.md",
            "content": _render_procedure_markdown(pid, body),
        })
    return packages


def _render_procedure_markdown(pid: str, body: dict[str, Any]) -> str:
    lines: list[str] = []
    name = str(body.get("name") or pid).strip()
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"id: `{pid}`")
    lines.append("")
    summary = (body.get("summary") or "").strip()
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")
    steps = body.get("steps") or []
    if isinstance(steps, list) and steps:
        lines.append("## Steps")
        lines.append("")
        for step in steps:
            if isinstance(step, str) and step.strip():
                lines.append(f"1. {step.strip()}")
            elif isinstance(step, dict):
                label = str(step.get("name") or step.get("id") or "step").strip()
                desc = str(step.get("description") or "").strip()
                if desc:
                    lines.append(f"1. **{label}** -- {desc}")
                else:
                    lines.append(f"1. **{label}**")
        lines.append("")
    notes = (body.get("notes") or "").strip()
    if notes:
        lines.append("## Notes")
        lines.append("")
        lines.append(notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Parameter families -- one per non-empty catalog
# ---------------------------------------------------------------------------


def build_parameter_families(state: dict[str, Any]) -> list[dict[str, Any]]:
    catalogs = state.get("catalogs") or {}
    if not isinstance(catalogs, dict):
        return []
    families: list[dict[str, Any]] = []
    for name in CATALOG_NAMES:
        entries = catalogs.get(name) or []
        if not isinstance(entries, list) or not entries:
            continue
        normalized = [
            _normalize_catalog_entry(e) for e in entries if isinstance(e, dict)
        ]
        normalized = [e for e in normalized if e.get("id")]
        if not normalized:
            continue
        families.append({
            "family_id": name,
            "filename": f"families/{name}.md",
            "content": _render_family_markdown(name, normalized),
            "json": {"entries": copy.deepcopy(normalized)},
        })
    return families


def _normalize_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    eid = str(entry.get("id") or "").strip()
    out: dict[str, Any] = {"id": eid}
    for key, value in entry.items():
        if key == "id":
            continue
        out[str(key)] = value
    return out


def _render_family_markdown(name: str, entries: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"# {name}", ""]
    for entry in entries:
        eid = str(entry.get("id") or "").strip()
        label = str(entry.get("name") or eid).strip()
        desc = str(entry.get("description") or "").strip()
        if eid:
            head = f"- **{label or eid}** (`{eid}`)"
            lines.append(f"{head} -- {desc}" if desc else head)
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["build_rule_packages", "build_parameter_families"]
