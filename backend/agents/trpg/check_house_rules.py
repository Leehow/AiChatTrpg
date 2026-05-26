"""Runtime house-rule overlays for compiled CHECK specs.

The stored Dice IR remains the canonical compiled output. House rules are a
small runtime patch layer read from ``ruleset.dice_ir.house_rules`` or
``ruleset.parsed_v6.house_rules`` so tables can tweak defaults without
recompiling the whole rulebook.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .check_resolver import CheckArgs


@dataclass
class HouseRuleApplication:
    ids: list[str] = field(default_factory=list)
    patches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        ids: list[str] = []
        for rule_id in self.ids:
            if rule_id and rule_id not in ids:
                ids.append(rule_id)
        return {
            "ids": ids,
            "patches": self.patches,
            "warnings": self.warnings,
        }


def collect_house_rules(ruleset: Any) -> list[dict[str, Any]]:
    """Return normalized house-rule overlay objects from a ruleset."""

    out: list[dict[str, Any]] = []
    artifact = getattr(ruleset, "dice_ir", None)
    parsed = getattr(ruleset, "parsed_v6", None)
    for source in (
        artifact.get("house_rules") if isinstance(artifact, dict) else None,
        parsed.get("house_rules") if isinstance(parsed, dict) else None,
    ):
        out.extend(_normalize_house_rules(source))
    return out


def apply_spec_house_rules(
    spec: dict[str, Any],
    house_rules: list[dict[str, Any]],
    *,
    procedure_id: str = "",
) -> dict[str, Any]:
    """Apply spec/runtime-stage patches to a check_spec copy."""

    if not house_rules:
        return copy.deepcopy(spec)
    out = copy.deepcopy(spec)
    applied = HouseRuleApplication()
    for rule in house_rules:
        if not _rule_matches(rule, out, procedure_id=procedure_id):
            continue
        rule_id = _rule_id(rule)
        for patch in _patches_for_stage(rule, {"spec", "runtime", "check_spec", ""}):
            if _apply_dict_patch(out, patch, applied):
                applied.ids.append(rule_id)
        for patch in _patches_for_stage(rule, {"request"}):
            applied.ids.append(rule_id)
            applied.patches.append(_patch_metadata(patch))
    if applied.patches or applied.warnings:
        out["_runtime_house_rules"] = applied.to_metadata()
    return out


def apply_request_house_rules(args: CheckArgs, spec: Mapping[str, Any] | None) -> CheckArgs:
    """Apply request-stage patches from the selected runtime spec."""

    meta = spec.get("_runtime_house_rules") if isinstance(spec, Mapping) else None
    patches = meta.get("patches") if isinstance(meta, Mapping) else None
    if not isinstance(patches, list):
        return args
    applied = HouseRuleApplication(
        ids=[str(x) for x in meta.get("ids") or []] if isinstance(meta, Mapping) else [],
    )
    work = CheckArgs(
        skill=args.skill,
        value=args.value,
        roll=args.roll,
        difficulty=args.difficulty,
        bonus=args.bonus,
        penalty=args.penalty,
        pool=args.pool,
        target=args.target,
        reason=args.reason,
        extras=copy.deepcopy(args.extras or {}),
    )
    for patch in patches:
        if isinstance(patch, Mapping) and str(patch.get("stage") or "") == "request":
            _apply_request_patch(work, patch, applied)
    if applied.patches or applied.warnings:
        work.extras["_house_rules"] = applied.to_metadata()
        if applied.warnings:
            warnings = work.extras.get("check_warnings")
            if not isinstance(warnings, list):
                warnings = []
            warnings.extend(applied.warnings)
            work.extras["check_warnings"] = warnings
    return work


def _normalize_house_rules(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, Mapping)]
    if isinstance(raw, Mapping):
        overlays = raw.get("overlays") or raw.get("rules")
        if isinstance(overlays, list):
            return [dict(x) for x in overlays if isinstance(x, Mapping)]
        if isinstance(raw.get("patches"), list):
            return [dict(raw)]
    return []


def _rule_matches(rule: Mapping[str, Any], spec: Mapping[str, Any], *, procedure_id: str) -> bool:
    target_pid = rule.get("procedure_id") or rule.get("procedure")
    if target_pid and str(target_pid) != str(procedure_id or ""):
        return False
    target_pids = rule.get("procedure_ids")
    if isinstance(target_pids, list) and target_pids:
        if str(procedure_id or "") not in {str(x) for x in target_pids}:
            return False
    target_engine = str(rule.get("engine") or "").strip()
    engine = str(spec.get("engine") or "").strip()
    if target_engine and _norm(target_engine) != _norm(engine):
        return False
    extends = str(rule.get("extends") or "").strip()
    if extends and not _engine_matches_extends(engine, extends):
        return False
    return True


def _patches_for_stage(rule: Mapping[str, Any], stages: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for patch in rule.get("patches") or []:
        if not isinstance(patch, Mapping):
            continue
        stage = str(patch.get("stage") or "")
        if stage in stages:
            payload = dict(patch)
            payload["_house_rule_id"] = _rule_id(rule)
            out.append(payload)
    return out


def _apply_dict_patch(target: dict[str, Any], patch: Mapping[str, Any], app: HouseRuleApplication) -> bool:
    op = str(patch.get("op") or "set").strip()
    path = str(patch.get("path") or "").strip()
    if not path:
        app.warnings.append(f"house rule {_patch_rule_id(patch)}: missing patch path")
        return False
    value = copy.deepcopy(patch.get("value"))
    if op == "set":
        _set_path(target, path, value)
    elif op == "merge":
        existing = _get_path(target, path)
        if not isinstance(existing, dict) or not isinstance(value, Mapping):
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: merge needs dict target/value")
            return False
        existing.update(copy.deepcopy(dict(value)))
    elif op == "append":
        existing = _get_path(target, path)
        if existing is None:
            _set_path(target, path, [value])
        elif isinstance(existing, list):
            existing.append(value)
        else:
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: append target is not a list")
            return False
    elif op == "add":
        existing = _get_path(target, path)
        if not isinstance(existing, (int, float)) or not isinstance(value, (int, float)):
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: add needs numeric target/value")
            return False
        _set_path(target, path, existing + value)
    else:
        app.warnings.append(f"house rule {_patch_rule_id(patch)}: unsupported op {op}")
        return False
    app.patches.append(_patch_metadata(patch))
    return True


def _apply_request_patch(args: CheckArgs, patch: Mapping[str, Any], app: HouseRuleApplication) -> None:
    op = str(patch.get("op") or "set").strip()
    path = str(patch.get("path") or "").strip()
    value = copy.deepcopy(patch.get("value"))
    if not path:
        app.warnings.append(f"house rule {_patch_rule_id(patch)}: missing request patch path")
        return
    target, key = _request_target(args, path)
    if op == "set":
        _request_set(target, key, value)
    elif op == "merge":
        existing = _request_get(target, key)
        if not isinstance(existing, dict) or not isinstance(value, Mapping):
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: request merge needs dict")
            return
        existing.update(copy.deepcopy(dict(value)))
    elif op == "append":
        existing = _request_get(target, key)
        if existing is None:
            _request_set(target, key, [value])
        elif isinstance(existing, list):
            existing.append(value)
        else:
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: request append target is not a list")
            return
    elif op in {"add", "add_modifier"}:
        current = _request_get(target, key)
        if current is None and op == "add_modifier":
            target, key = args, "value"
            current = args.value
        if not isinstance(current, (int, float)) or not isinstance(value, (int, float)):
            app.warnings.append(f"house rule {_patch_rule_id(patch)}: request add needs numeric target/value")
            return
        _request_set(target, key, current + value)
    else:
        app.warnings.append(f"house rule {_patch_rule_id(patch)}: unsupported request op {op}")
        return
    app.patches.append(_patch_metadata(patch))


def _request_target(args: CheckArgs, path: str) -> tuple[Any, str]:
    if "." not in path and hasattr(args, path):
        return args, path
    if path.startswith("params."):
        root = args.extras.setdefault("params", {})
        parts = path.split(".")[1:]
    else:
        root = args.extras
        parts = path.split(".")
    cursor = root
    for part in parts[:-1]:
        next_node = cursor.get(part) if isinstance(cursor, dict) else None
        if not isinstance(next_node, dict):
            next_node = {}
            cursor[part] = next_node
        cursor = next_node
    return cursor, parts[-1]


def _request_get(target: Any, key: str) -> Any:
    if isinstance(target, CheckArgs):
        return getattr(target, key)
    if isinstance(target, dict):
        return target.get(key)
    return None


def _request_set(target: Any, key: str, value: Any) -> None:
    if isinstance(target, CheckArgs):
        setattr(target, key, value)
    elif isinstance(target, dict):
        target[key] = value


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def _get_path(target: dict[str, Any], path: str) -> Any:
    cursor: Any = target
    for part in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def _patch_metadata(patch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": _patch_rule_id(patch),
        "stage": str(patch.get("stage") or ""),
        "op": str(patch.get("op") or "set"),
        "path": str(patch.get("path") or ""),
        "value": copy.deepcopy(patch.get("value")),
    }


def _patch_rule_id(patch: Mapping[str, Any]) -> str:
    return str(patch.get("_house_rule_id") or patch.get("rule_id") or "house_rule")


def _engine_matches_extends(engine: str, extends: str) -> bool:
    if not extends:
        return True
    e = _norm(engine)
    x = _norm(extends)
    aliases = {
        "coc7e": {"coc7ed100", "coc7e", "coc"},
        "coc7": {"coc7ed100", "coc7e", "coc"},
        "brp": {"brpd100", "brp"},
        "d20": {"d20vsdc", "d20"},
        "pbta": {"pbta2d6", "pbta"},
    }
    accepted = aliases.get(x, {x})
    return e in accepted or any(token in e for token in accepted)


def _rule_id(rule: Mapping[str, Any]) -> str:
    return str(rule.get("id") or rule.get("name") or "house_rule")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())
