"""Deterministic mechanical seed for setup-time character generation.

The LLM is still useful for identity, occupation fit, backstory, equipment,
and filling ruleset-specific prose fields. Mechanical values are different:
when the ruleset gives recognizable character-creation dice, this adapter
rolls them in Python first, records an audit trace, and lets the LLM fill the
card around those fixed values.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from agents.trpg.check_resolver import CheckArgs, parse_roll_list
from agents.trpg.check_runtime import auto_roll_for_check


COC_CORE_ATTRS = ("STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU")
DEEP_FILES_ATTRS = ("STR", "CON", "SIZ", "DEX", "PRE", "INT", "POW", "EDU")


@dataclass
class CharacterMechanicalSeed:
    supported: bool
    system_family: str = ""
    seed: str = ""
    attributes: dict[str, int] = field(default_factory=dict)
    thresholds: dict[str, dict[str, int]] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    roll_trace: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "system_family": self.system_family,
            "seed": self.seed,
            "attributes": self.attributes,
            "thresholds": self.thresholds,
            "derived": self.derived,
            "roll_trace": self.roll_trace,
            "notes": self.notes,
        }

    def prompt_block(self) -> str:
        if not self.supported:
            return ""
        payload = self.to_metadata()
        return (
            "## Mechanical Character Generation Seed\n"
            "The backend has already rolled the mechanical character values. "
            "You MUST copy these exact values into the character card wherever "
            "the template has corresponding fields. Do not reroll, average, "
            "or replace them. Use the LLM only for identity, occupation, "
            "skill allocation, backstory, equipment, and prose fields that are "
            "not fixed by this seed.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )


def build_character_mechanical_seed(
    ruleset: Any,
    *,
    session_id: str = "",
    user_seed: str = "",
    mode: str = "",
    transcript: str = "",
) -> CharacterMechanicalSeed:
    """Build deterministic chargen rolls for recognized ruleset templates."""

    raw = getattr(ruleset, "parsed_v6", None)
    parsed = raw if isinstance(raw, dict) else {}
    sheet = parsed.get("character_sheet") if isinstance(parsed.get("character_sheet"), dict) else {}
    template = sheet.get("template_json") if isinstance(sheet.get("template_json"), (dict, list)) else {}
    guide = str(sheet.get("guide_content") or "")
    core = str(parsed.get("core_rules") or "")
    search_text = "\n".join([guide, core, _json_dumps(template)])
    attr_keys = _collect_attribute_keys(template)
    family = _detect_family(attr_keys, search_text)
    if not family:
        return CharacterMechanicalSeed(
            supported=False,
            notes=["No recognized character-generation dice contract found."],
        )

    base_seed = _base_seed(
        ruleset,
        session_id=session_id,
        user_seed=user_seed,
        mode=mode,
        transcript=transcript,
    )
    attrs = DEEP_FILES_ATTRS if family == "deep_d100_horror" else COC_CORE_ATTRS
    if "PRE" in attr_keys and family == "coc7_percentile":
        attrs = DEEP_FILES_ATTRS
        family = "deep_d100_horror"

    roll_trace: list[dict[str, Any]] = []
    values: dict[str, int] = {}
    for attr in attrs:
        expr = _attribute_expression(attr)
        value, trace = _roll_attribute(attr, expr, f"{base_seed}:{attr}")
        values[attr] = value
        roll_trace.append(trace)

    wants_luck = (
        "LUCK" in attr_keys
        or "FATE" in attr_keys
        or _contains_any(search_text, ("luck", "幸运", "fate"))
    )
    if wants_luck:
        luck_key = "FATE" if family == "deep_d100_horror" or "FATE" in attr_keys else "LUCK"
        luck_value, luck_trace = _roll_attribute(luck_key, "3d6*5", f"{base_seed}:{luck_key}")
        values[luck_key] = luck_value
        roll_trace.append(luck_trace)

    thresholds = {
        key: _thresholds(value)
        for key, value in values.items()
        if key not in {"FATE", "LUCK"}
    }
    derived = _derive_values(values, family)
    return CharacterMechanicalSeed(
        supported=True,
        system_family=family,
        seed=base_seed,
        attributes=values,
        thresholds=thresholds,
        derived=derived,
        roll_trace=roll_trace,
        notes=[
            "Age adjustments, occupation skill allocation, finances, equipment, and backstory remain LLM-assisted unless the ruleset later exposes a stricter chargen IR.",
        ],
    )


def apply_character_mechanical_seed(
    card: dict[str, Any],
    seed: CharacterMechanicalSeed | Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay mechanical seed values into a generated card copy."""

    if not isinstance(card, dict):
        return card
    meta = seed.to_metadata() if isinstance(seed, CharacterMechanicalSeed) else dict(seed or {})
    if not meta.get("supported"):
        return copy.deepcopy(card)
    out = copy.deepcopy(card)
    roots = [out]
    if isinstance(out.get("fields"), dict):
        roots.append(out["fields"])
    attrs = {
        str(k).upper(): int(v)
        for k, v in (meta.get("attributes") or {}).items()
        if isinstance(v, (int, float))
    }
    thresholds = meta.get("thresholds") if isinstance(meta.get("thresholds"), dict) else {}
    derived = meta.get("derived") if isinstance(meta.get("derived"), dict) else {}
    for root in roots:
        if isinstance(root, dict):
            _apply_attributes(root, attrs, thresholds)
            _apply_derived(root, attrs, derived)
            _apply_skill_bases(root, attrs)
    out.setdefault("_generation_audit", {})
    if isinstance(out["_generation_audit"], dict):
        out["_generation_audit"]["mechanical_seed"] = meta
    return out


def character_seed_summary(seed: CharacterMechanicalSeed) -> str:
    if not seed.supported:
        return "mechanical_seed=unsupported"
    return (
        f"mechanical_seed={seed.system_family} "
        f"attrs={len(seed.attributes)} rolls={len(seed.roll_trace)}"
    )


def _detect_family(attr_keys: set[str], text: str) -> str:
    has_coc_attrs = len(set(COC_CORE_ATTRS).intersection(attr_keys)) >= 6
    has_deep_attrs = len(set(DEEP_FILES_ATTRS).intersection(attr_keys)) >= 6
    lower = text.lower()
    deep_signature = (
        "PRE" in attr_keys
        or "FATE" in attr_keys
        or re.search(r"\bfate\b", lower)
        or "深层档案" in text
    )
    if deep_signature and (has_deep_attrs or not has_coc_attrs):
        return "deep_d100_horror"
    if has_coc_attrs or "3d6 × 5" in lower or "3d6 x 5" in lower or "3d6*5" in lower:
        return "coc7_percentile"
    return ""


def _collect_attribute_keys(template: Any) -> set[str]:
    out: set[str] = set()

    def walk(value: Any, parent: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                text = str(key).strip()
                norm = text.upper()
                if norm in set(COC_CORE_ATTRS) | set(DEEP_FILES_ATTRS) | {"LUCK", "FATE"}:
                    out.add(norm)
                if parent.lower() in {"attributes", "characteristics"}:
                    out.add(norm)
                walk(child, text)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent)

    walk(template)
    return out


def _base_seed(
    ruleset: Any,
    *,
    session_id: str,
    user_seed: str,
    mode: str,
    transcript: str,
) -> str:
    raw = "|".join([
        "chatrpg-character-v1",
        str(getattr(ruleset, "id", "") or ""),
        str(session_id or ""),
        str(mode or ""),
        str(user_seed or ""),
        hashlib.sha256(str(transcript or "").encode("utf-8")).hexdigest()[:16],
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _attribute_expression(attr: str) -> str:
    return "(2d6+6)*5" if attr in {"SIZ", "INT", "EDU"} else "3d6*5"


def _roll_attribute(attr: str, expr: str, seed: str) -> tuple[int, dict[str, Any]]:
    if expr == "3d6*5":
        dice_expr = "3d6"
        modifier = 0
    elif expr == "(2d6+6)*5":
        dice_expr = "2d6"
        modifier = 6
    else:
        dice_expr = "3d6"
        modifier = 0
    sample = auto_roll_for_check(
        CheckArgs(roll="auto", extras={"roll_seed": seed}),
        {
            "engine": "generic_resolution_v1",
            "ir": {
                "steps": [
                    {"op": "read_rolls", "source_arg": "roll", "expr": dice_expr}
                ]
            },
        },
    )
    rolls = parse_roll_list(sample.value)
    total = sum(rolls) * 5
    if modifier:
        total = (sum(rolls) + modifier) * 5
    return total, {
        "id": f"attribute.{attr}",
        "label": attr,
        "expression": expr,
        "roll_expression": sample.expression,
        "roll_expressions": sample.roll_expressions,
        "roll_sources": sample.roll_sources,
        "roll_seed": sample.seed,
        "rolls": rolls,
        "modifier": modifier,
        "multiplier": 5,
        "total": total,
    }


def _thresholds(value: int) -> dict[str, int]:
    return {"full": value, "half": value // 2, "fifth": value // 5}


def _derive_values(attrs: Mapping[str, int], family: str) -> dict[str, Any]:
    con = int(attrs.get("CON") or 0)
    siz = int(attrs.get("SIZ") or 0)
    pow_ = int(attrs.get("POW") or 0)
    dex = int(attrs.get("DEX") or 0)
    str_ = int(attrs.get("STR") or 0)
    int_ = int(attrs.get("INT") or 0)
    edu = int(attrs.get("EDU") or 0)
    hp = math.floor((con + siz) / 10) if con and siz else 0
    mp = math.floor(pow_ / 5) if pow_ else 0
    db, build = _damage_bonus_and_build(str_ + siz)
    derived: dict[str, Any] = {
        "HP": hp,
        "max_HP": hp,
        "hit_points": {"current": hp, "maximum": hp, "half_maximum": hp // 2},
        "MP": mp,
        "magic_points": {"current": mp, "maximum": mp},
        "damage_bonus": db,
        "build": build,
        "MOV": _move_rate(str_, dex, siz),
        "dodge": _thresholds(dex // 2),
        "idea": _thresholds(int_),
        "know": _thresholds(edu),
    }
    if family == "deep_d100_horror":
        dcp = 0
        derived.update({
            "FOC": mp,
            "max_FOC": mp,
            "STA": pow_,
            "max_STA": 99 - dcp,
            "DCP": dcp,
            "FATE": attrs.get("FATE") or attrs.get("LUCK"),
            "DB": db,
        })
    else:
        derived.update({
            "SAN": pow_,
            "max_SAN": 99,
            "luck": attrs.get("LUCK") or attrs.get("FATE"),
            "sanity": {
                "current": pow_,
                "starting": pow_,
                "maximum": 99,
                "daily_loss_starting_value": pow_,
                "daily_loss_current_total": 0,
            },
        })
    return derived


def _move_rate(str_: int, dex: int, siz: int) -> int:
    if str_ and dex and siz:
        if str_ > siz and dex > siz:
            return 9
        if str_ < siz and dex < siz:
            return 7
    return 8


def _damage_bonus_and_build(total: int) -> tuple[str, int]:
    if total <= 64:
        return "-2", -2
    if total <= 84:
        return "-1", -1
    if total <= 124:
        return "0", 0
    if total <= 164:
        return "+1d4", 1
    if total <= 204:
        return "+1d6", 2
    if total <= 284:
        return "+2d6", 3
    if total <= 364:
        return "+3d6", 4
    return "+4d6", 5


def _apply_attributes(
    root: dict[str, Any],
    attrs: Mapping[str, int],
    thresholds: Mapping[str, Any],
) -> None:
    attr_container = _first_dict(root, ("attributes", "characteristics"))
    if attr_container is None:
        return
    key_map = {str(k).upper(): k for k in attr_container.keys()}
    for attr, value in attrs.items():
        target_key = key_map.get(attr)
        if target_key is None:
            continue
        existing = attr_container.get(target_key)
        th = thresholds.get(attr) if isinstance(thresholds.get(attr), dict) else _thresholds(value)
        if isinstance(existing, dict):
            _set_if_present(existing, ("value", "full", "current", "starting"), value)
            if "value" not in existing and "full" not in existing:
                existing["value"] = value
            if "half" in existing:
                existing["half"] = int(th.get("half", value // 2))
            if "fifth" in existing:
                existing["fifth"] = int(th.get("fifth", value // 5))
        else:
            attr_container[target_key] = value


def _apply_derived(
    root: dict[str, Any],
    attrs: Mapping[str, int],
    derived: Mapping[str, Any],
) -> None:
    for name in ("derived", "derived_values", "resources"):
        target = root.get(name)
        if isinstance(target, dict):
            _apply_derived_container(target, derived)
    if "derived" not in root and isinstance(root.get("fields"), dict):
        target = root["fields"].get("derived")
        if isinstance(target, dict):
            _apply_derived_container(target, derived)


def _apply_derived_container(target: dict[str, Any], derived: Mapping[str, Any]) -> None:
    simple_keys = (
        "HP", "max_HP", "FOC", "max_FOC", "STA", "max_STA", "DCP", "FATE",
        "MOV", "DB", "damage_bonus", "build", "movement_rate",
    )
    for key in simple_keys:
        value = derived.get("MOV") if key == "movement_rate" else derived.get(key)
        _set_case_insensitive(target, key, value)
    move_key = _case_key(target, "move_rate")
    if move_key is not None and isinstance(target[move_key], dict) and derived.get("MOV") is not None:
        target[move_key]["value"] = derived["MOV"]
        if target[move_key].get("base_before_age") in (None, ""):
            target[move_key]["base_before_age"] = derived["MOV"]
    _apply_nested_resource(target, ("hit_points", "hit_point_track"), derived.get("hit_points"))
    _apply_nested_resource(target, ("magic_points", "magic_point_track"), derived.get("magic_points"))
    _apply_nested_resource(target, ("sanity", "sanity_track"), derived.get("sanity"))
    _apply_nested_resource(target, ("luck", "luck_track"), {"current": derived.get("luck"), "starting": derived.get("luck")})
    for key, value in {
        "dodge_base_from_dex_half": (derived.get("dodge") or {}).get("full")
        if isinstance(derived.get("dodge"), dict) else None,
        "idea": derived.get("idea"),
        "know": derived.get("know"),
    }.items():
        if value is None:
            continue
        existing_key = _case_key(target, key)
        if existing_key is None:
            continue
        if isinstance(target[existing_key], dict) and isinstance(value, dict):
            target[existing_key].update(value)
        else:
            target[existing_key] = value


def _apply_nested_resource(
    target: dict[str, Any],
    names: Iterable[str],
    value: Any,
) -> None:
    if not isinstance(value, dict):
        return
    for name in names:
        key = _case_key(target, name)
        if key is None:
            continue
        if isinstance(target[key], dict):
            for sub_key, sub_val in value.items():
                if sub_val is not None:
                    target[key][sub_key] = sub_val


def _apply_skill_bases(root: dict[str, Any], attrs: Mapping[str, int]) -> None:
    dex = int(attrs.get("DEX") or 0)
    if not dex:
        return
    dodge = dex // 2
    skills = root.get("skills")
    if isinstance(skills, list):
        for item in skills:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().lower() != "dodge":
                continue
            for key in ("base", "value", "full"):
                if key in item or key != "base":
                    item[key] = dodge
            item["half"] = dodge // 2
            item["fifth"] = dodge // 5


def _first_dict(root: dict[str, Any], names: Iterable[str]) -> dict[str, Any] | None:
    for name in names:
        value = root.get(name)
        if isinstance(value, dict):
            return value
    return None


def _set_if_present(target: dict[str, Any], keys: Iterable[str], value: Any) -> None:
    for key in keys:
        if key in target:
            target[key] = value


def _set_case_insensitive(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    existing = _case_key(target, key)
    if existing is not None:
        target[existing] = value


def _case_key(target: Mapping[str, Any], key: str) -> str | None:
    key_lower = key.lower()
    for existing in target.keys():
        if str(existing).lower() == key_lower:
            return str(existing)
    return None


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    lower = text.lower()
    return any(str(needle).lower() in lower for needle in needles)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return ""
