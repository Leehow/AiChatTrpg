"""NPC psychology fields — inner state + player_knowledge / interest model.

Ported from chatlab's ``agents/trpg/npc_player_knowledge.py`` (initialization
half — the per-turn ``apply_player_knowledge_updates`` belongs in a future
post-process pass and is intentionally left out for the first revision)
and ``agents/trpg/npc_presim.py``'s ``_persist_inner_state`` helper.

What lives on each NPC dict after these helpers run:

- ``inner_state`` (dict)
    - ``motivation`` — what they want right now (string)
    - ``emotional_state`` — current mood (string)
    - ``secret_agenda`` — GM-only hidden goal (string, optional)
    - ``thought_log`` — recent inner monologue, capped at 5 entries

- ``player_knowledge`` (dict)
    - ``level`` (int 0-5) — how much they know about the PC
    - ``interest`` (int 0-10) — urgency to engage with the PC
    - ``interest_profile`` — frozen behavior band derived from interest
    - ``interest_drive`` — kind / floor / decay-on-goal-satisfied
    - ``relationship`` — "stranger" / "preexisting_relationship" / "plot_informed"
    - ``access`` — list of authorisations to learn off-scene
    - ``can_know_off_scene`` — bool
    - ``known_facts`` / ``exposure_log`` / ``interaction_goals``
    - ``obtained_goals`` / ``affinity_topics`` / ``shared_affinities``
    - ``preferred_conversation_topics``
    - ``notes`` — narrative context

Both blocks are populated at NPC creation and live alongside the existing
visibility (``name_revealed`` / ``player_known_name``) and stat
(``params``) fields. Per-turn updates can layer on later by writing to the
same shapes.

This module is the public facade. Rubric/regex constants live in
``psychology_constants``; small text-cleaning helpers live in
``psychology_helpers``. Public callers should keep importing from
``services.trpg_npc.psychology`` — the surface (constants and the seven
``ensure_*`` / ``derive_*`` / ``append_*`` / ``player_interest_profile``
helpers) is preserved here.
"""

from __future__ import annotations

from typing import Any

from services.trpg_npc.psychology_constants import (
    INNER_STATE_THOUGHT_CAP,
    INTEREST_RUBRIC,
    _AFFINITY_DRIVE_RE,
    _GOAL_RE,
    _HIGH_INTEREST_RE,
    _LOW_INTEREST_RE,
    _PLOT_ACCESS_RE,
    _PREEXISTING_RE,
    _SOCIAL_DRIVE_RE,
)
from services.trpg_npc.psychology_helpers import (
    _clamp_int,
    _clean_text,
    _first_clause,
    _inner_state_blob,
    _pc_display_name,
    _split_topic_text,
    _text_blob,
    _unique_strings,
)


__all__ = [
    "INNER_STATE_THOUGHT_CAP",
    "INTEREST_RUBRIC",
    "append_inner_thought",
    "derive_interaction_drive",
    "derive_player_interest",
    "ensure_npc_inner_state",
    "ensure_npc_player_knowledge",
    "ensure_npc_psychology",
    "player_interest_profile",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def player_interest_profile(value: Any) -> dict[str, Any]:
    """Return the fixed behavioural band for an NPC's PC interaction drive."""
    score = _clamp_int(value, 0, 10, 3)
    for band in INTEREST_RUBRIC:
        if band["min"] <= score <= band["max"]:
            return {
                "band": band["band"],
                "label": band["label"],
                "guidance": band["guidance"],
            }
    band = INTEREST_RUBRIC[2]
    return {"band": band["band"], "label": band["label"], "guidance": band["guidance"]}


def derive_interaction_drive(npc: dict[str, Any]) -> dict[str, Any]:
    """Derive ``{kind, score, decays_on_goal_satisfied, floor, reason}``."""
    blob = _text_blob(npc)
    inner_blob = _inner_state_blob(npc)
    full_blob = f"{blob} {inner_blob}".strip()
    has_preexisting = bool(npc.get("from_bond") or _PREEXISTING_RE.search(blob))
    has_plot_access = bool(_PLOT_ACCESS_RE.search(full_blob))
    has_goal = bool(_GOAL_RE.search(full_blob))
    has_high_interest = bool(_HIGH_INTEREST_RE.search(full_blob))
    has_low_interest = bool(_LOW_INTEREST_RE.search(full_blob))

    intrinsic = _base_intrinsic_drive(
        full_blob,
        has_preexisting=has_preexisting,
        has_high_interest=has_high_interest,
        has_low_interest=has_low_interest,
    )

    goal_score = 8 if has_goal else 7 if has_plot_access else 0
    if goal_score and intrinsic["score"] >= 5:
        drive = {
            "kind": "mixed",
            "score": max(goal_score, intrinsic["score"]),
            "decays_on_goal_satisfied": True,
            "floor": intrinsic["score"],
            "reason": (
                "Goal-driven pursuit layered over intrinsic/social/professional "
                f"drive: {intrinsic['reason']}"
            ),
        }
    elif goal_score:
        drive = {
            "kind": "goal_driven",
            "score": goal_score,
            "decays_on_goal_satisfied": True,
            "floor": 3,
            "reason": (
                "Wants information, an item, access, leverage, or another "
                "objective from the PC."
            ),
        }
    else:
        drive = intrinsic

    explicit = npc.get("player_interest")
    if explicit is not None:
        drive["score"] = _clamp_int(explicit, 0, 10, drive["score"])
        drive["floor"] = min(_clamp_int(drive.get("floor"), 0, 10, 0), drive["score"])

    return {
        "kind": str(drive.get("kind") or "neutral"),
        "decays_on_goal_satisfied": bool(drive.get("decays_on_goal_satisfied")),
        "floor": _clamp_int(drive.get("floor"), 0, 10, 0),
        "reason": _clean_text(drive.get("reason"), 220),
        "score": _clamp_int(drive.get("score"), 0, 10, 3),
    }


def derive_player_interest(npc: dict[str, Any]) -> int:
    return derive_interaction_drive(npc)["score"]


def ensure_npc_player_knowledge(
    npc: dict[str, Any],
    pc: dict[str, Any] | None = None,
) -> bool:
    """Ensure ``npc["player_knowledge"]`` exists and is normalised.

    Existing fields the GM or earlier LLM passes have set are preserved;
    defaults only fill gaps. Returns True when the dict was mutated.
    """
    if not isinstance(npc, dict):
        return False
    default = _default_player_knowledge(npc, pc)
    existing = npc.get("player_knowledge")
    if not isinstance(existing, dict):
        npc["player_knowledge"] = default
        return True

    changed = False
    for key, value in default.items():
        if key not in existing:
            existing[key] = value
            changed = True

    # Normalise drive even when caller provided one.
    drive = _normalize_interest_drive(existing.get("interest_drive"), default["interest_drive"], existing.get("interest", default["interest"]))
    if existing.get("interest_drive") != drive:
        existing["interest_drive"] = drive
        changed = True

    if _sync_interest_profile(existing):
        changed = True
    return changed


def ensure_npc_inner_state(npc: dict[str, Any]) -> bool:
    """Seed ``npc["inner_state"]`` from existing motivation/role text.

    Idempotent. The presim pass (when added later) will overwrite these
    fields per turn — we just give the GM something non-empty for the
    first scene the NPC appears in.
    """
    if not isinstance(npc, dict):
        return False
    inner = npc.get("inner_state")
    if isinstance(inner, dict) and inner.get("motivation") and inner.get("emotional_state"):
        return False
    if not isinstance(inner, dict):
        inner = {}

    motivation = _clean_text(
        npc.get("motivation")
        or _first_clause(npc.get("role"))
        or _first_clause(npc.get("description"))
        or _first_clause(npc.get("summary"))
        or "(none yet)",
        180,
    )
    emotional_state = _clean_text(
        npc.get("emotional_state") or npc.get("personality") or "neutral, watchful",
        80,
    )
    secret_agenda = _clean_text(
        npc.get("secret_agenda") or npc.get("agenda") or "",
        180,
    )
    thought_log: list[str] = list(inner.get("thought_log") or [])[-INNER_STATE_THOUGHT_CAP:]

    new_inner = {
        "motivation": motivation,
        "emotional_state": emotional_state,
        "secret_agenda": secret_agenda,
        "thought_log": thought_log,
    }
    if new_inner == inner:
        return False
    npc["inner_state"] = new_inner
    return True


def append_inner_thought(npc: dict[str, Any], thought: str) -> bool:
    """Append a presim-style inner thought, capped at ``INNER_STATE_THOUGHT_CAP``."""
    if not isinstance(npc, dict):
        return False
    text = _clean_text(thought, 200)
    if not text:
        return False
    inner = npc.get("inner_state")
    if not isinstance(inner, dict):
        inner = {}
    log = list(inner.get("thought_log") or [])
    log.append(text)
    inner["thought_log"] = log[-INNER_STATE_THOUGHT_CAP:]
    npc["inner_state"] = inner
    return True


def ensure_npc_psychology(
    npc: dict[str, Any],
    *,
    pc: dict[str, Any] | None = None,
) -> bool:
    """One-call helper: ensures both inner_state and player_knowledge exist."""
    inner_changed = ensure_npc_inner_state(npc)
    knowledge_changed = ensure_npc_player_knowledge(npc, pc)
    return bool(inner_changed or knowledge_changed)


# ---------------------------------------------------------------------------
# Internal helpers (mirrored from chatlab, simplified to the bits we need)
# ---------------------------------------------------------------------------


def _default_player_knowledge(
    npc: dict[str, Any],
    pc: dict[str, Any] | None,
) -> dict[str, Any]:
    blob = _text_blob(npc)
    # LLM extraction (when available) is more accurate than regex pattern
    # matching — the model just read the entire character JSON or NPC card
    # and decided what relationship label fits. If it set a hint we honour
    # it; otherwise we fall back to the keyword regexes.
    hint = str(npc.get("llm_relationship_hint") or "").strip().lower()
    has_bond = bool(npc.get("from_bond") or isinstance(npc.get("bond_context"), dict))
    if hint == "preexisting_relationship":
        preexisting, plot_access = True, False
    elif hint == "plot_informed":
        preexisting, plot_access = False, True
    elif hint == "stranger":
        preexisting, plot_access = has_bond, False
    else:
        preexisting = has_bond or bool(_PREEXISTING_RE.search(blob))
        plot_access = bool(_PLOT_ACCESS_RE.search(blob))

    level = 0
    relationship = "stranger"
    access = ["same_scene_observed"]
    can_know_off_scene = False
    known_facts: list[str] = []
    notes = (
        "Starts as a stranger. They may notice visible behaviour, but do not "
        "know the PC's name, background, or goals until exposed in scene."
    )

    pc_name = _pc_display_name(pc)
    if preexisting:
        level = 4
        relationship = "preexisting_relationship"
        access = ["preexisting_relationship", "same_scene_observed"]
        can_know_off_scene = True
        notes = (
            "Has a pre-established relationship with the PC; may know "
            "relationship-appropriate facts."
        )
        if pc_name:
            known_facts.append(f"Knows the PC's name: {pc_name}.")
        bond = npc.get("bond_context")
        if isinstance(bond, dict):
            connection = _clean_text(bond.get("connection") or bond.get("relationship"))
            if connection:
                known_facts.append(f"Pre-existing bond/context: {connection}.")
    elif plot_access:
        level = 2
        relationship = "plot_informed"
        access = ["plot_required", "same_scene_observed"]
        can_know_off_scene = True
        notes = (
            "Has limited plot-authorised access. Use only facts explicitly "
            "in known_facts/exposure_log, not the full PC sheet."
        )

    drive = derive_interaction_drive(npc)
    interest = drive["score"]
    # Honour any LLM-seeded `interest_drive` dict on the NPC (kind, reason,
    # decay) — the model just classified this character explicitly and is
    # more accurate than the keyword regex for things like "前妻 wants the
    # PC out of trouble" → relationship-driven, not the regex's neutral
    # default. Pass the seeded dict as ``value`` so ``_normalize_interest_drive``
    # prefers it over the regex-derived ``default``.
    seeded_drive = npc.get("interest_drive") if isinstance(npc.get("interest_drive"), dict) else None
    knowledge = {
        "schema_version": 1,
        "level": level,
        "interest": interest,
        "relationship": relationship,
        "access": access,
        "can_know_off_scene": can_know_off_scene,
        "known_facts": known_facts,
        "exposure_log": [],
        "interaction_goals": _derive_interaction_goals(npc),
        "obtained_goals": [],
        "affinity_topics": _derive_affinity_topics(npc),
        "shared_affinities": [],
        "preferred_conversation_topics": [],
        "interest_drive": _normalize_interest_drive(seeded_drive, drive, interest),
        "notes": notes,
    }
    _sync_interest_profile(knowledge)
    return knowledge


def _base_intrinsic_drive(
    full_blob: str,
    *,
    has_preexisting: bool,
    has_high_interest: bool,
    has_low_interest: bool,
) -> dict[str, Any]:
    if _AFFINITY_DRIVE_RE.search(full_blob):
        score, kind, reason = 6, "affinity", "Shared hobby, profession, background, or affinity with the PC."
    elif _SOCIAL_DRIVE_RE.search(full_blob):
        score, kind, reason = 6, "social", "Intrinsic social drive, curiosity, loneliness, or boredom."
    elif has_preexisting:
        score, kind, reason = 4, "relationship", "Pre-existing relationship or bond with the PC."
    elif has_high_interest:
        score, kind, reason = 6, "professional", "Role or profession naturally encourages engagement and questions."
    elif has_low_interest:
        score, kind, reason = 2, "neutral", "Low personal drive; interaction is mostly passive."
    else:
        score, kind, reason = 3, "neutral", "Default contextual willingness to interact."

    if has_low_interest and kind not in {"affinity", "social"}:
        score = min(score, 4 if has_high_interest else 2)

    return {
        "kind": kind,
        "score": score,
        "decays_on_goal_satisfied": False,
        "floor": score,
        "reason": reason,
    }


def _normalize_interest_drive(
    value: Any,
    default: dict[str, Any],
    score: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    score_int = _clamp_int(score, 0, 10, int(default.get("score") or 3))
    floor = _clamp_int(value.get("floor"), 0, 10, int(default.get("floor") or 0))
    floor = min(floor, score_int)
    return {
        "kind": _clean_text(value.get("kind") or default.get("kind") or "neutral", 60),
        "decays_on_goal_satisfied": bool(
            value.get(
                "decays_on_goal_satisfied",
                default.get("decays_on_goal_satisfied", False),
            )
        ),
        "floor": floor,
        "reason": _clean_text(value.get("reason") or default.get("reason"), 220),
        "score": score_int,
    }


def _sync_interest_profile(knowledge: dict[str, Any]) -> bool:
    score = _clamp_int(knowledge.get("interest"), 0, 10, 3)
    changed = knowledge.get("interest") != score
    knowledge["interest"] = score
    profile = player_interest_profile(score)
    if knowledge.get("interest_profile") != profile:
        knowledge["interest_profile"] = profile
        changed = True
    return changed


def _derive_interaction_goals(npc: dict[str, Any]) -> list[str]:
    raw: list[Any] = []
    for field in ("interaction_goals", "goals", "objective", "objectives", "agenda", "motivation"):
        value = npc.get(field)
        if isinstance(value, list):
            raw.extend(value)
        elif isinstance(value, str) and value.strip():
            raw.append(value)
    return _unique_strings(raw, limit=6)


def _derive_affinity_topics(npc: dict[str, Any]) -> list[str]:
    raw: list[Any] = []
    for field in ("affinity_topics", "preferred_topics", "interests", "hobbies"):
        value = npc.get(field)
        if isinstance(value, list):
            raw.extend(value)
        elif isinstance(value, str) and value.strip():
            raw.extend(_split_topic_text(value))
    return _unique_strings(raw, limit=10)
