"""Runtime lookup helpers for compiled TRPG check specs.

Rulesets can carry many compiled ``check_specs`` in ``dice_ir`` while older
runtime code expects one flat ``check_spec`` dict. This module keeps both
shapes compatible: callers can pass the returned runtime dict anywhere a
single spec was accepted, and procedure-aware paths can select a specific
compiled procedure by id.
"""

from __future__ import annotations

import copy
from typing import Any

from .check_house_rules import apply_spec_house_rules, collect_house_rules


_RUNTIME_CHECK_SPECS_KEY = "_runtime_check_specs"
_RUNTIME_PROCEDURE_INDEX_KEY = "_runtime_procedure_index"
_RUNTIME_SEMANTIC_INDEX_KEY = "_runtime_semantic_index"
_RUNTIME_KEYS = {
    _RUNTIME_CHECK_SPECS_KEY,
    _RUNTIME_PROCEDURE_INDEX_KEY,
    _RUNTIME_SEMANTIC_INDEX_KEY,
    "_runtime_ruleset_name",
    "_runtime_default_procedure_id",
    "_runtime_applied_procedure_id",
    "_runtime_procedure_id",
    "_runtime_house_rules",
}


def build_runtime_check_spec(ruleset: Any) -> dict[str, Any]:
    """Return a backwards-compatible runtime spec for one ruleset."""

    artifact = (
        getattr(ruleset, "dice_ir", None)
        if isinstance(getattr(ruleset, "dice_ir", None), dict) else {}
    )
    compiled = _compiled_block(artifact)
    check_specs = _check_specs_by_procedure(compiled)
    procedure_index = _procedure_index(compiled, check_specs)
    semantic_index = _semantic_index(compiled, procedure_index)
    default_id = str(compiled.get("default_procedure_id") or "")
    house_rules = collect_house_rules(ruleset)
    applied = artifact.get("applied_check_spec") if isinstance(artifact, dict) else None
    applied_id = (
        str(applied.get("procedure_id") or "").strip()
        if isinstance(applied, dict) else ""
    )

    spec = (
        copy.deepcopy(getattr(ruleset, "check_spec", None))
        if isinstance(getattr(ruleset, "check_spec", None), dict) else {}
    )
    if not spec:
        default_spec = _spec_for_procedure(compiled, default_id)
        if default_spec:
            spec = copy.deepcopy(default_spec)
    if spec:
        spec = apply_spec_house_rules(
            spec,
            house_rules,
            procedure_id=applied_id or default_id,
        )
    if check_specs:
        check_specs = {
            pid: apply_spec_house_rules(item, house_rules, procedure_id=pid)
            for pid, item in check_specs.items()
        }

    title = str(getattr(ruleset, "book_title", "") or "").strip()
    if title:
        spec.setdefault("_runtime_ruleset_name", title)
    if default_id:
        spec.setdefault("_runtime_default_procedure_id", default_id)
    if applied_id:
        spec.setdefault("_runtime_applied_procedure_id", applied_id)
    if check_specs:
        spec[_RUNTIME_CHECK_SPECS_KEY] = check_specs
    if procedure_index:
        spec[_RUNTIME_PROCEDURE_INDEX_KEY] = procedure_index
    if semantic_index:
        spec[_RUNTIME_SEMANTIC_INDEX_KEY] = semantic_index
    return spec


def select_check_spec(
    runtime_spec: dict[str, Any] | None,
    procedure_id: str | None,
) -> dict[str, Any]:
    """Pick the compiled spec for ``procedure_id`` when available."""

    current = copy.deepcopy(runtime_spec) if isinstance(runtime_spec, dict) else {}
    pid = str(procedure_id or "").strip()
    specs = current.get(_RUNTIME_CHECK_SPECS_KEY)
    if pid and isinstance(specs, dict) and isinstance(specs.get(pid), dict):
        chosen = copy.deepcopy(specs[pid])
        _copy_runtime_metadata(current, chosen)
        chosen["_runtime_procedure_id"] = pid
        return chosen
    if pid:
        current["_runtime_procedure_id"] = pid
    elif current.get("_runtime_applied_procedure_id"):
        current["_runtime_procedure_id"] = str(current["_runtime_applied_procedure_id"])
    elif current.get("_runtime_default_procedure_id"):
        current["_runtime_procedure_id"] = str(current["_runtime_default_procedure_id"])
    return current


def public_check_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    """Strip runtime-only keys before persisting or exposing a spec."""

    if not isinstance(spec, dict):
        return {}
    return {k: copy.deepcopy(v) for k, v in spec.items() if k not in _RUNTIME_KEYS}


def _compiled_block(artifact: dict[str, Any]) -> dict[str, Any]:
    package = artifact.get("package") if isinstance(artifact, dict) else None
    compiled = package.get("compiled") if isinstance(package, dict) else None
    return compiled if isinstance(compiled, dict) else {}


def _check_specs_by_procedure(compiled: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in compiled.get("check_specs") or []:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("procedure_id") or "").strip()
        spec = entry.get("check_spec")
        if pid and isinstance(spec, dict):
            out[pid] = copy.deepcopy(spec)
    return out


def _spec_for_procedure(
    compiled: dict[str, Any],
    procedure_id: str,
) -> dict[str, Any] | None:
    candidates = compiled.get("check_specs") or []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        if procedure_id and str(entry.get("procedure_id") or "") != procedure_id:
            continue
        spec = entry.get("check_spec")
        if isinstance(spec, dict):
            return spec
    if candidates:
        first = candidates[0]
        if isinstance(first, dict) and isinstance(first.get("check_spec"), dict):
            return first["check_spec"]
    return None


def _copy_runtime_metadata(src: dict[str, Any], dest: dict[str, Any]) -> None:
    for key in _RUNTIME_KEYS - {_RUNTIME_CHECK_SPECS_KEY, "_runtime_procedure_id"}:
        if key in src:
            dest.setdefault(key, copy.deepcopy(src[key]))
    if _RUNTIME_CHECK_SPECS_KEY in src:
        dest[_RUNTIME_CHECK_SPECS_KEY] = copy.deepcopy(src[_RUNTIME_CHECK_SPECS_KEY])


def _procedure_index(
    compiled: dict[str, Any],
    check_specs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    raw_index = compiled.get("procedure_index")
    out = (
        copy.deepcopy(raw_index)
        if isinstance(raw_index, dict) else {}
    )
    entries = compiled.get("check_specs") or []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("procedure_id") or "").strip()
        if not pid:
            continue
        spec = check_specs.get(pid)
        if spec is None:
            raw_spec = entry.get("check_spec")
            spec = raw_spec if isinstance(raw_spec, dict) else {}
        meta = out.get(pid) if isinstance(out.get(pid), dict) else {}
        meta = dict(meta)
        meta.setdefault("check_specs_index", idx)
        meta.setdefault("engine", str((spec or {}).get("engine") or ""))
        name = entry.get("name") or entry.get("title") or _deep_get(spec, ("ir", "name"))
        if name:
            meta.setdefault("name", str(name))
        aliases = _string_list(entry.get("aliases")) or _string_list(spec.get("aliases"))
        if not aliases:
            aliases = _string_list(_deep_get(spec, ("ir", "routing", "aliases")))
        if not aliases:
            aliases = _string_list(_deep_get(spec, ("ir", "aliases")))
        if aliases:
            meta["aliases"] = _merge_string_lists(meta.get("aliases"), aliases)
        tags = (
            _string_list(entry.get("semantic_tags"))
            or _string_list(spec.get("semantic_tags"))
            or _string_list(_deep_get(spec, ("ir", "routing", "semantic_tags")))
            or _string_list(_deep_get(spec, ("ir", "semantic_tags")))
        )
        if tags:
            meta["semantic_tags"] = _merge_string_lists(meta.get("semantic_tags"), tags)
        out[pid] = meta
    return out


def _semantic_index(
    compiled: dict[str, Any],
    procedure_index: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    raw_index = compiled.get("semantic_index")
    if isinstance(raw_index, dict):
        for tag, raw_pids in raw_index.items():
            pids = _string_list(raw_pids)
            if pids:
                out[str(tag)] = pids
    for pid, meta in procedure_index.items():
        if not isinstance(meta, dict):
            continue
        for tag in _string_list(meta.get("semantic_tags")):
            bucket = out.setdefault(tag, [])
            if pid not in bucket:
                bucket.append(pid)
    return out


def _string_list(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item or "").strip()]
    return []


def _merge_string_lists(first: Any, second: Any) -> list[str]:
    out: list[str] = []
    for item in [*_string_list(first), *_string_list(second)]:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _deep_get(obj: Any, path: tuple[str, ...]) -> Any:
    cur = obj
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur
