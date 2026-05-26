"""Eager NPC parameter generation for AiChatTrpg sessions.

Newly-created NPCs (from character intake or in-game ``[CREATE_NPC]``
markers) start with a name, gender, and a short summary — but no
mechanical stats. Without numbers the GM cannot resolve dice opposition
against them, so this module asks an LLM to fill in a *minimal* set of
ruleset-appropriate stats per NPC: core attributes, an HP-like pool,
maybe one or two role-specific knobs.

Ported from chatlab's ``agents/trpg/npc_param_gen.py``. Adapted to
chatrpg's storage shape:

- chatrpg: ``session.memory_state["npcs"][]`` + single ``session.character``
- chatlab: ``session.characters["npcs"][]`` + ``session.characters["pc"]``

Failures are logged and counted on the NPC entry — after MAX_FAILURES
attempts the NPC is left without params rather than burning tokens
forever.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.trpg.llm_json import (
    call_llm_json_task,
    extract_json_object,
)


logger = logging.getLogger("chatrpg.trpg.npc_param_gen")

MAX_FAILURES = 2
_DESCRIPTION_FIELDS = ("summary", "description", "role", "appearance")
_PERSONALITY_FIELDS = ("personality", "voice_hint", "traits")


NPC_PARAM_GEN_PROMPT = """You are a TRPG game mechanics designer. Generate ONLY the numerical
stats an NPC needs for dice checks — nothing else.

## NPC Profile
Name: {npc_name}
Description: {npc_description}
Personality: {npc_personality}

## PC Stats (reference for parameter names and value ranges)
{pc_stats}

## Rules Reference (how checks work)
{rules_hint}

Instructions:
- Generate ONLY numerical parameters used in dice rolls and opposition checks.
- Use the SAME stat names as the PC (e.g. if PC has "qualities", NPC gets "qualities").
- Do NOT generate narrative fields (descriptions, relationships, backstory, sanctioned behaviors, retirement options, requisitions, etc.)
- Do NOT generate tracking fields (commendations, demerits, mission records, etc.)
- ONLY output: core stats, HP/QA pools, and at most 1-2 special numeric traits unique to this NPC's role.
- Values should be narratively fair:
  * Weak civilian → stats well below PC average
  * Trained professional → roughly equal to PC
  * Elite/supernatural → above PC average
- Keep parameter names in English snake_case.

Output ONLY valid JSON (no markdown fences):
{{"params": {{"stat_name": value, ...}}, "reasoning": "one-line justification"}}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_missing_npc_params(
    npcs: list[dict[str, Any]],
    *,
    session_character: dict[str, Any] | None,
    rules_hint: str,
    model: str,
    base_url: str,
    api_key: str,
) -> int:
    """Fill ``npc["params"]`` on every NPC in ``npcs`` that still lacks it.

    Mutates the NPC dicts in place. The caller is responsible for
    ``flag_modified(session, "memory_state")`` and committing — this
    function makes no DB calls itself. Returns the number of NPCs that
    received freshly-generated params.
    """
    pc_stats = _format_pc_param_hint(session_character)
    count = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if npc.get("params"):
            continue
        if int(npc.get("params_gen_failures") or 0) >= MAX_FAILURES:
            continue
        name = str(npc.get("name") or "").strip()
        if not name:
            continue
        try:
            result = await _generate_single_npc_params(
                npc,
                pc_stats=pc_stats,
                rules_hint=rules_hint,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )
        except Exception:
            fails = int(npc.get("params_gen_failures") or 0) + 1
            npc["params_gen_failures"] = fails
            logger.warning(
                "[chatrpg] npc params gen failed for '%s' (%d/%d)",
                name, fails, MAX_FAILURES, exc_info=True,
            )
            continue

        params = result.get("params") if isinstance(result, dict) else None
        if not isinstance(params, dict) or not params:
            fails = int(npc.get("params_gen_failures") or 0) + 1
            npc["params_gen_failures"] = fails
            continue

        npc["params"] = params
        reasoning = (
            str(result.get("reasoning") or "").strip()
            if isinstance(result, dict)
            else ""
        )
        if reasoning:
            npc["params_context"] = reasoning
        npc.pop("params_gen_failures", None)
        count += 1
        logger.info(
            "[chatrpg] npc params generated for '%s': %s (%s)",
            name, list(params.keys()), reasoning,
        )
    return count


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _generate_single_npc_params(
    npc: dict[str, Any],
    *,
    pc_stats: str,
    rules_hint: str,
    model: str,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    description = _first_text(npc, _DESCRIPTION_FIELDS)[:400]
    personality = _first_text(npc, _PERSONALITY_FIELDS)[:200]

    user_message = NPC_PARAM_GEN_PROMPT.format(
        npc_name=npc.get("name") or npc.get("key") or "Unknown",
        npc_description=description or "(no description)",
        npc_personality=personality or "(no personality cues)",
        pc_stats=pc_stats or "(no PC stats available)",
        rules_hint=rules_hint or "(no rules reference available)",
    )

    raw = await call_llm_json_task(
        stage="npc_param_gen",
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix="You are a TRPG mechanics designer. Output strict JSON only.",
        user_message=user_message,
        stream=False,
    )
    return _parse_param_response(raw)


def _parse_param_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text.strip())
    try:
        return extract_json_object(text)
    except Exception:
        # extract_json_object is strict; fall back to plain json.loads in case
        # the model produced clean JSON without surrounding noise.
        return json.loads(text)


def _format_pc_param_hint(pc: dict[str, Any] | None) -> str:
    """Flatten PC numeric fields into a compact ``key=value`` list."""
    if not isinstance(pc, dict):
        return ""
    parts: list[str] = []
    for key, value in pc.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{key}={value}")
        elif isinstance(value, dict):
            inner = {
                k: v for k, v in value.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            if inner:
                parts.append(f"{key}={json.dumps(inner, ensure_ascii=False)}")
    return ", ".join(parts[:15])


def _first_text(obj: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            joined = " / ".join(str(p).strip() for p in value if str(p).strip())
            if joined:
                return joined
    return ""


def build_rules_hint_from_parsed_v6(parsed_v6: dict[str, Any] | None) -> str:
    """Best-effort rules excerpt for the param-gen prompt.

    chatrpg's parsed_v6 is large (~150KB), so we slice instead of dumping.
    Prefer the companion summary + first rule package, capped at ~2KB.
    """
    if not isinstance(parsed_v6, dict):
        return ""
    chunks: list[str] = []
    companion = parsed_v6.get("companion")
    if isinstance(companion, dict):
        text = str(companion.get("content") or "").strip()
        if text:
            chunks.append(text[:1200])
    packages = parsed_v6.get("rule_packages")
    if isinstance(packages, dict):
        for kind in ("combat", "abilities", "creation"):
            pkg = packages.get(kind)
            if isinstance(pkg, dict):
                text = str(pkg.get("content") or "").strip()
                if text:
                    chunks.append(f"# {kind}\n{text[:600]}")
                    break
    return "\n\n".join(chunks)[:2000]
