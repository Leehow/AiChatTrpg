"""LLM-driven extractor: resident_prompt → check_spec JSON.

Runs once at rule-parse time. The extractor reads the already-distilled
``resident_prompt`` of a ruleset and figures out which deterministic
check engine to use at runtime, plus any engine-specific knobs
(DC defaults, per-die targets, tier labels, etc.).

Result shape (stored in ``TrpgRuleset.check_spec`` as JSON)::

    {
      "engine": "coc_7e_d100",        # see check_engines for options
      "labels": {                     # optional — override engine defaults
        "critical": "大成功", "extreme": "极难成功",
        "hard": "困难成功",  "regular": "常规成功",
        "failure": "失败",   "fumble": "大失败"
      },
      "default_dc": 12,               # d20_vs_dc only
      "hit_threshold": 10,            # pbta_2d6 only
      "partial_threshold": 7,         # pbta_2d6 only
      "per_die_target": 3,            # pool_count_n only
      "crit_successes": 4,            # pool_count_n only (opt-in)
      "notes": "short verbatim note"  # free-form caveats for audit
    }

Non-fatal on failure — callers should fall through to a ``custom_llm``
marker so the GM narrates the outcome unchanged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from .pipeline_helpers import apply_trpg_request_defaults, build_trpg_client

logger = logging.getLogger("chatlab.trpg")


VALID_ENGINES = {
    "coc_7e_d100", "brp_d100", "d20_vs_dc",
    "pbta_2d6", "pool_count_n", "custom_llm",
}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_EXTRACT_PROMPT = """You are a TRPG rules analyst. Read the always-on rules below and pick the single check-resolution engine that best matches the system.

## Engines (pick exactly one)
- coc_7e_d100 — Call of Cthulhu 7e / Delta Green style. Roll 1d100, compare vs skill. Hard = skill/2, Extreme = skill/5. Fumble band 96-100 (or 100 if skill >= 50). 01 = critical. Difficulty tier requested by GM.
- brp_d100    — Basic Roleplaying d100, no hard/extreme tiers. Only Special (skill/5) and Regular (<= skill). Fumble same as CoC.
- d20_vs_dc   — D&D 5e / Pathfinder. Roll 1d20 + modifier vs DC. 20 = critical, 1 = fumble.
- pbta_2d6    — Powered by the Apocalypse. Roll 2d6 + stat. >=10 hit, 7-9 partial, <=6 miss.
- pool_count_n — Dice pool systems (WOD, Triangle Agency). Roll N dice, count how many land >= per_die_target.
- custom_llm  — Fallback ONLY when no deterministic engine fits. Produces no numeric comparison; GM narrates.

## Optional engine knobs (only include if rules specify)
- d20_vs_dc: "default_dc" (integer, 10-20 typical) if rules state a default DC.
- pbta_2d6: "hit_threshold" (default 10), "partial_threshold" (default 7).
- pool_count_n: "per_die_target" (integer, 2-6 typical), "crit_successes" (integer, opt-in; omit if rules do not define a separate crit tier).

## Optional label overrides
If the rules consistently use non-standard terminology for success/failure tiers, put overrides under "labels". Keys must match the engine's tier keys. Values should be verbatim from the rules. Omit "labels" entirely if the rules use mainstream TRPG terms already covered by defaults.

Engine tier keys:
- coc_7e_d100: critical, extreme, hard, regular, failure, fumble
- brp_d100: special, regular, failure, fumble
- d20_vs_dc: critical, success, failure, fumble
- pbta_2d6: hit, partial, miss
- pool_count_n: crit, success, failure

## Rules
{resident_prompt}

## Output format
Return ONLY a JSON object. No code fences, no commentary, no prose.

Example minimal: {{"engine": "coc_7e_d100"}}
Example with overrides: {{"engine": "pool_count_n", "per_die_target": 3, "crit_successes": 4, "labels": {{"crit": "完美执行", "success": "执行", "failure": "偏离"}}}}

If you genuinely cannot tell, return {{"engine": "custom_llm", "notes": "<one short reason>"}}."""


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def analyze_resident_prompt_for_check_spec(
    resident_prompt: str,
    model: str,
    base_url: str,
    api_key: str,
) -> Dict[str, Any]:
    """Extract a ``check_spec`` dict from a ruleset's resident rules.

    Returns ``{}`` on any failure so the caller can choose whether to
    fall back to ``custom_llm`` or leave the column NULL.
    """
    if not resident_prompt or not resident_prompt.strip():
        return {}

    try:
        client = build_trpg_client(base_url=base_url, api_key=api_key)
        kwargs = apply_trpg_request_defaults({
            "model": model,
            "messages": [{
                "role": "user",
                "content": _EXTRACT_PROMPT.format(
                    resident_prompt=resident_prompt.strip()[:12000],
                ),
            }],
        })
        r = await client.chat.completions.create(**kwargs)
        text = (r.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(
            "[TRPG] check_spec extraction call failed: %s", e, exc_info=True,
        )
        return {}

    spec = _parse_spec_json(text)
    if not spec:
        return {}
    spec = _normalize_spec(spec)
    if not spec:
        return {}
    logger.info("[TRPG] check_spec extracted: %s", spec)
    return spec


# ---------------------------------------------------------------------------
# JSON parsing + normalization
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def _parse_spec_json(raw: str) -> Dict[str, Any]:
    """Best-effort JSON parse. Strips code fences and finds the first object."""
    if not raw:
        return {}
    cleaned = _FENCE_RE.sub("", raw).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        logger.warning("[TRPG] check_spec: no JSON object found in model output")
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("[TRPG] check_spec: JSON decode failed: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


# Integer knobs recognized per-engine; unknown keys are silently dropped.
_INT_KNOBS = {
    "d20_vs_dc": ("default_dc",),
    "pbta_2d6": ("hit_threshold", "partial_threshold"),
    "pool_count_n": ("per_die_target", "crit_successes"),
}


def _coerce_int(val: Any) -> Any:
    """Return int if coercible, else drop by returning None."""
    if isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _normalize_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce schema: valid engine, clean knobs, safe labels, notes text."""
    engine = str(raw.get("engine") or "").strip().lower()
    if engine not in VALID_ENGINES:
        logger.warning(
            "[TRPG] check_spec: engine '%s' not recognized, coercing to custom_llm",
            engine,
        )
        return {"engine": "custom_llm", "notes": f"unknown engine '{engine}'"}

    out: Dict[str, Any] = {"engine": engine}

    # Engine-specific integer knobs.
    for key in _INT_KNOBS.get(engine, ()):
        if key in raw:
            v = _coerce_int(raw[key])
            if v is not None and v > 0:
                out[key] = v

    # Label overrides — only keep string→string entries.
    labels = raw.get("labels")
    if isinstance(labels, dict):
        clean_labels = {
            str(k): str(v).strip()
            for k, v in labels.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }
        if clean_labels:
            out["labels"] = clean_labels

    # Free-form note; cap length so a runaway model response can't bloat the row.
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        out["notes"] = notes.strip()[:400]

    return out
