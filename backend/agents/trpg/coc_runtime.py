"""Runtime helpers for Call of Cthulhu style d100 checks.

These helpers keep CoC marker handling deterministic even when a v6 ruleset
has a generic compiled ``check_spec`` attached. The old CoC d100 engine is the
authoritative runtime for live ``[CHECK]`` / ``[CONTEST]`` markers because it
knows the 01 critical, extreme/hard thresholds, and fumble band directly.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Optional

COC_D100_ENGINE = "coc_7e_d100"
GENERIC_CHECK_ENGINES = {"", "custom_llm", "generic_resolution_v1"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _word_norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", _norm(value)).strip()


def is_coc_marker_system(system: Any) -> bool:
    """Return true for explicit marker system ids such as ``coc_7e``."""

    text = _word_norm(system).replace(" ", "_")
    return text in {
        "coc",
        "coc7",
        "coc_7e",
        "coc7e",
        "call_of_cthulhu",
        "cthulhu",
        "克苏鲁",
    }


def is_coc_ruleset_name(name: Any) -> bool:
    """Best-effort CoC ruleset name detection for runtime fallback."""

    text = _word_norm(name)
    if not text:
        return False
    if "call of cthulhu" in text or "cthulhu" in text or "克苏鲁" in text:
        return True
    compact = text.replace(" ", "")
    if compact.startswith("coc") or "coc" in compact:
        return True
    return bool(re.search(r"(^| )coc($| |[0-9])", text))


def coerce_coc_d100_check_spec(
    spec: Optional[Dict[str, Any]],
    *,
    ruleset_name: Any = None,
    system: Any = None,
) -> Dict[str, Any]:
    """Return a CoC d100 runtime spec when the context clearly asks for CoC.

    Explicit marker systems win. For session-level coercion we only replace
    missing/custom/generic specs, so non-CoC deterministic engines remain intact.
    """

    current = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    if ruleset_name is None:
        ruleset_name = current.get("_runtime_ruleset_name")
    engine = _norm(current.get("engine"))
    if engine == COC_D100_ENGINE:
        if ruleset_name and "_runtime_ruleset_name" not in current:
            current["_runtime_ruleset_name"] = str(ruleset_name)
        return current

    explicit_coc_marker = is_coc_marker_system(system)
    coc_ruleset = is_coc_ruleset_name(ruleset_name)
    explicit_procedure = bool(current.get("_runtime_procedure_id"))
    should_coerce = explicit_coc_marker or (
        coc_ruleset and engine in GENERIC_CHECK_ENGINES and not explicit_procedure
    )
    if not should_coerce:
        return current

    coerced: Dict[str, Any] = {"engine": COC_D100_ENGINE}
    labels = current.get("labels")
    if isinstance(labels, dict):
        coerced["labels"] = labels
    coerced["_runtime_coerced_from"] = engine or "missing"
    if ruleset_name:
        coerced["_runtime_ruleset_name"] = str(ruleset_name)
    return coerced


def effective_check_spec_for_session(session: Any) -> Dict[str, Any]:
    """Resolve the check spec used by live inline marker replacement."""

    ruleset_name = ""
    try:
        from .pipeline_helpers import get_session_ruleset

        ruleset = get_session_ruleset(session)
        ruleset_name = getattr(ruleset, "name", "") or ""
    except Exception:
        ruleset_name = ""
    effective = coerce_coc_d100_check_spec(
        getattr(session, "check_spec", None),
        ruleset_name=ruleset_name,
    )
    if ruleset_name and "_runtime_ruleset_name" not in effective:
        effective["_runtime_ruleset_name"] = str(ruleset_name)
    return effective


def coc_tier_rule_effect(tier: str, *, contest: bool = False) -> str:
    """Player-facing rule consequence for CoC special tiers."""

    key = _norm(tier)
    if key == "critical":
        if contest:
            return (
                "大成功比普通成功获得更强优势；若命中，按极限/穿刺伤害分支结算，"
                "并应给出明确的额外战术收益。"
            )
        return (
            "大成功应在常规成功外给出明确额外收益，例如更快、更安静、"
            "更完整的线索、后续难度降低或更有利位置。"
        )
    if key == "fumble":
        if contest:
            return (
                "大失败比普通失败更糟，必须带来额外麻烦，例如失衡、掉落、暴露、"
                "误伤、给对手机会或额外 HP/SAN/时间代价。"
            )
        return (
            "大失败应比普通失败更糟，必须带来额外麻烦，例如暴露位置、损坏/丢失物品、"
            "误伤、警觉升级、资源损耗或额外 HP/SAN/时间代价。"
        )
    return ""
