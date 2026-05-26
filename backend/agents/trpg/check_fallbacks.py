"""System-scoped fallback routing for semantic CHECK procedures.

The core runtime stays ruleset-agnostic: it executes the selected procedure.
This module is the narrow extension point for system-specific primitives when
the uploaded/compiled ruleset did not provide a procedure that the engine can
otherwise infer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .check_resolver import CheckArgs


@dataclass(frozen=True)
class FallbackRoute:
    """A semantic CHECK route, optionally with a full fallback spec."""

    procedure_id: str
    spec: dict[str, Any] | None = None
    reason: str = ""


def semantic_check_route(
    args: CheckArgs,
    runtime_spec: dict[str, Any],
) -> FallbackRoute | None:
    """Return a catalog or system-scoped route for semantic CHECKs."""

    route = _compiled_procedure_catalog_route(args, runtime_spec)
    if route is not None:
        return route
    for selector in (_coc_sanity_route,):
        route = selector(args, runtime_spec)
        if route is not None:
            return route
    return None


_SANITY_LABELS = {
    "san",
    "sancheck",
    "sanroll",
    "sanity",
    "sanitycheck",
    "sanityroll",
    "sanityloss",
    "sanloss",
    "理智",
    "理智检定",
    "理智损失",
}

_SCORE_EXACT_ALIAS = 300
_SCORE_NORMALIZED_ALIAS = 240
_SCORE_SEMANTIC_TAG = 180


def _compiled_procedure_catalog_route(
    args: CheckArgs,
    runtime_spec: dict[str, Any],
) -> FallbackRoute | None:
    labels = _request_labels(args)
    if not labels:
        return None
    procedure_index = _runtime_procedure_index(runtime_spec)
    if not procedure_index:
        return None
    candidates: dict[str, tuple[int, list[str]]] = {}
    for pid, meta in procedure_index.items():
        if not isinstance(meta, dict):
            continue
        score, reasons = _score_catalog_candidate(labels, pid, meta)
        if score <= 0:
            continue
        prev = candidates.get(pid)
        if prev is None or score > prev[0]:
            candidates[pid] = (score, reasons)
    if not candidates:
        return None
    ranked = sorted(candidates.items(), key=lambda item: item[1][0], reverse=True)
    top_pid, (top_score, top_reasons) = ranked[0]
    runner_up = ranked[1][1][0] if len(ranked) > 1 else 0
    if top_score >= 250 and top_score - runner_up >= 80:
        return FallbackRoute(top_pid, reason=", ".join(top_reasons))
    if top_score >= 180 and len(ranked) == 1:
        return FallbackRoute(top_pid, reason=", ".join(top_reasons))
    return None


def _score_catalog_candidate(
    labels: list[str],
    procedure_id: str,
    meta: dict[str, Any],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    aliases = _string_list(meta.get("aliases"))
    name = str(meta.get("name") or "").strip()
    if name:
        aliases.append(name)
    aliases.append(procedure_id)
    tags = _string_list(meta.get("semantic_tags"))
    for label in labels:
        raw_label = str(label or "").strip().lower()
        normalized_label = _compact_label(label)
        for alias in aliases:
            raw_alias = str(alias or "").strip().lower()
            normalized_alias = _compact_label(alias)
            if raw_label and raw_label == raw_alias:
                if _SCORE_EXACT_ALIAS > score:
                    score = _SCORE_EXACT_ALIAS
                    reasons = [f"alias:{alias}"]
            elif normalized_label and normalized_label == normalized_alias:
                if _SCORE_NORMALIZED_ALIAS > score:
                    score = _SCORE_NORMALIZED_ALIAS
                    reasons = [f"normalized_alias:{alias}"]
        for tag in tags:
            if normalized_label and normalized_label == _compact_label(tag):
                if _SCORE_SEMANTIC_TAG > score:
                    score = _SCORE_SEMANTIC_TAG
                    reasons = [f"semantic_tag:{tag}"]
    return score, reasons


def _runtime_procedure_index(runtime_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_index = runtime_spec.get("_runtime_procedure_index")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw_index, dict):
        for pid, meta in raw_index.items():
            if str(pid or "").strip() and isinstance(meta, dict):
                out[str(pid)] = dict(meta)
    specs = runtime_spec.get("_runtime_check_specs")
    if isinstance(specs, dict):
        for pid, spec in specs.items():
            if not str(pid or "").strip() or not isinstance(spec, dict):
                continue
            meta = out.get(str(pid), {})
            aliases = (
                _string_list(spec.get("aliases"))
                or _string_list(_deep_get(spec, ("ir", "routing", "aliases")))
                or _string_list(_deep_get(spec, ("ir", "aliases")))
            )
            tags = (
                _string_list(spec.get("semantic_tags"))
                or _string_list(_deep_get(spec, ("ir", "routing", "semantic_tags")))
                or _string_list(_deep_get(spec, ("ir", "semantic_tags")))
            )
            if aliases:
                meta["aliases"] = _merge_string_lists(meta.get("aliases"), aliases)
            if tags:
                meta["semantic_tags"] = _merge_string_lists(meta.get("semantic_tags"), tags)
            name = _deep_get(spec, ("ir", "name"))
            if name:
                meta.setdefault("name", str(name))
            out[str(pid)] = meta
    semantic_index = runtime_spec.get("_runtime_semantic_index")
    if isinstance(semantic_index, dict):
        for tag, raw_pids in semantic_index.items():
            for pid in _string_list(raw_pids):
                meta = out.setdefault(pid, {})
                meta["semantic_tags"] = _merge_string_lists(meta.get("semantic_tags"), [str(tag)])
    return out


def _request_labels(args: CheckArgs) -> list[str]:
    extras = args.extras or {}
    out: list[str] = []
    for value in (
        args.skill,
        extras.get("skill"),
        extras.get("check"),
        extras.get("check_key"),
        extras.get("param"),
    ):
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
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


def _coc_sanity_route(
    args: CheckArgs,
    runtime_spec: dict[str, Any],
) -> FallbackRoute | None:
    if not _is_sanity_check_request(args):
        return None
    procedure_id = _find_sanity_procedure_id(runtime_spec)
    if procedure_id:
        return FallbackRoute(
            procedure_id=procedure_id,
            reason="compiled CoC sanity procedure",
        )
    if not _looks_like_coc_runtime(runtime_spec):
        return None
    return FallbackRoute(
        procedure_id="coc7.sanity_roll",
        spec=_fallback_coc_sanity_spec(runtime_spec),
        reason="built-in CoC sanity fallback",
    )


def _is_sanity_check_request(args: CheckArgs) -> bool:
    extras = args.extras or {}
    candidates = (
        args.skill,
        extras.get("skill"),
        extras.get("check"),
        extras.get("check_key"),
        extras.get("param"),
    )
    return any(_is_sanity_label(value) for value in candidates)


def _is_sanity_label(value: Any) -> bool:
    compact = _compact_label(value)
    if not compact:
        return False
    simplified = compact.replace("检定", "").replace("损失", "").replace("值", "")
    return compact in _SANITY_LABELS or simplified in _SANITY_LABELS


def _find_sanity_procedure_id(runtime_spec: dict[str, Any]) -> str:
    specs = runtime_spec.get("_runtime_check_specs")
    if not isinstance(specs, dict):
        return ""
    best_pid = ""
    best_score = 0
    for raw_pid, spec in specs.items():
        pid = str(raw_pid or "").strip()
        if not pid or not isinstance(spec, dict):
            continue
        score = _sanity_procedure_score(pid, spec)
        if score > best_score:
            best_score = score
            best_pid = pid
    return best_pid


def _sanity_procedure_score(procedure_id: str, spec: dict[str, Any]) -> int:
    raw_id = procedure_id.lower()
    compact_id = _compact_label(procedure_id)
    ir = spec.get("ir") if isinstance(spec, dict) else None
    ir_id = str(ir.get("id") or "").lower() if isinstance(ir, dict) else ""
    ir_name = str(ir.get("name") or "").lower() if isinstance(ir, dict) else ""
    combined = " ".join(part for part in (raw_id, ir_id, ir_name) if part)
    compact_combined = _compact_label(combined)
    if "sanity_roll" in combined or compact_id.endswith("sanityroll"):
        return 100
    if re.search(r"(?<!in)sanity", combined) or "理智" in compact_combined:
        return 80
    if re.search(r"(^|[._:-])san($|[._:-])", raw_id):
        return 60
    if "sanroll" in compact_combined or "sancheck" in compact_combined:
        return 40
    return 0


def _looks_like_coc_runtime(runtime_spec: dict[str, Any]) -> bool:
    text_parts = [
        runtime_spec.get("_runtime_ruleset_name"),
        runtime_spec.get("_runtime_default_procedure_id"),
        runtime_spec.get("_runtime_applied_procedure_id"),
        runtime_spec.get("_runtime_procedure_id"),
        runtime_spec.get("engine"),
    ]
    specs = runtime_spec.get("_runtime_check_specs")
    if isinstance(specs, dict):
        text_parts.extend(str(pid) for pid in specs)
    text = _compact_label(" ".join(str(part or "") for part in text_parts))
    return "callofcthulhu" in text or "cthulhu" in text or "coc" in text


def _fallback_coc_sanity_spec(runtime_spec: dict[str, Any]) -> dict[str, Any]:
    from .check_ir.packs.coc7 import coc7_sanity_roll_check_spec

    ruleset_name = str(runtime_spec.get("_runtime_ruleset_name") or "Call of Cthulhu")
    spec = coc7_sanity_roll_check_spec()
    spec = {
        **spec,
        "_runtime_procedure_id": "coc7.sanity_roll",
        "_runtime_default_procedure_id": runtime_spec.get("_runtime_default_procedure_id", ""),
        "_runtime_applied_procedure_id": runtime_spec.get("_runtime_applied_procedure_id", ""),
        "_runtime_ruleset_name": runtime_spec.get("_runtime_ruleset_name", ruleset_name),
    }
    return {key: value for key, value in spec.items() if value not in (None, "")}


def _compact_label(value: Any) -> str:
    return re.sub(r"[\s_\-:：/（）()\[\].]+", "", str(value or "").strip().lower())
