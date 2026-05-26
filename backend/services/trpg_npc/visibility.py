"""Player-vs-true-name handling for TRPG NPCs.

Ported from chatlab's ``agents/trpg/npc_store.py`` (``derive_public_npc_name``
+ ``ensure_npc_visibility_fields``). The split:

- ``name`` — the GM's true / canonical name. Always present internally.
- ``player_known_name`` — what the player sees. Either the true name (when
  revealed) or a description-derived label like "瘦长皮卡司机".
- ``name_revealed`` — bool gate. When false, the sidebar UI shows
  ``player_known_name``; when true it shows ``name``. The debug memory
  panel always shows both.

This module is the single source of truth for that logic so future
backend places (marker apply, IC sync, etc.) can call the same helper.
"""

from __future__ import annotations

import re
from typing import Any


_FEMALE_HINT_RE = re.compile(
    r"女性|女人|女子|女孩|少女|妇女|\bfemale\b|\bwoman\b|\bgirl\b|\blady\b|\bmother\b",
    re.I,
)
_MALE_HINT_RE = re.compile(
    r"男性|男人|男子|男孩|少年|\bmale\b|\bman\b|\bboy\b|\bgentleman\b|\bfather\b",
    re.I,
)
_DOCTOR_HINT_RE = re.compile(r"医生|医师|护士|\bdoctor\b|\bphysician\b|\bnurse\b", re.I)
_GUARD_HINT_RE = re.compile(r"守卫|保安|警卫|\bguard\b|\bsecurity\b", re.I)
_PRIEST_HINT_RE = re.compile(r"牧师|祭司|僧侣|\bpriest\b|\bmonk\b", re.I)
_OFFICER_HINT_RE = re.compile(r"警官|警员|警探|\bofficer\b|\bdetective\b|\bcop\b", re.I)

_FEMALE_GENDER_VALUES = {"female", "f", "女", "女性"}
_MALE_GENDER_VALUES = {"male", "m", "男", "男性"}

_LABEL_NORMALISE_RE = re.compile(r"[\s·•・/／,，、;；:：\-_—|]+")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_female_gender(value: str) -> bool:
    return (value or "").strip().lower() in _FEMALE_GENDER_VALUES


def is_male_gender(value: str) -> bool:
    return (value or "").strip().lower() in _MALE_GENDER_VALUES


def derive_public_npc_name(npc: dict[str, Any]) -> str:
    """Best-effort player-facing label that does NOT reveal the true name.

    Used as the seed for ``player_known_name`` when the GM creates an NPC
    whose name the player has not learned in fiction. Prefer existing
    description-style fields the GM may have already filled in; otherwise
    synthesise from gender / age / role / appearance hints.
    """
    if not isinstance(npc, dict):
        return ""

    true_name = str(npc.get("name") or "").strip()

    # 1. GM-provided alternate labels — already player-safe.
    for field in (
        "player_known_name", "claimed_name", "known_as", "public_name",
        "display_label", "short_name", "nickname",
    ):
        candidate = str(npc.get(field) or "").strip()
        if candidate and not _same_identity_label(candidate, true_name):
            return candidate

    # 2. Role / title — e.g. "ex-wife in San Antonio" → "ex-wife".
    for field in ("role", "title"):
        candidate = str(npc.get(field) or "").strip()
        if candidate and not _same_identity_label(candidate, true_name):
            # Only the leading clause; "前妻，住在圣安东尼奥" → "前妻".
            short = re.split(r"[，,;；。.]\s*", candidate, maxsplit=1)[0].strip()
            return short or candidate

    description = " ".join(
        str(npc.get(field) or "")
        for field in ("description", "summary", "appearance", "brief")
    )
    gender_hint = str(npc.get("gender") or "").strip().lower()
    has_cjk = bool(re.search(r"[一-鿿]", description + true_name))

    female = (
        is_female_gender(gender_hint)
        or bool(_FEMALE_HINT_RE.search(description))
    )
    male = (
        is_male_gender(gender_hint)
        or bool(_MALE_HINT_RE.search(description))
    )

    if has_cjk:
        if _DOCTOR_HINT_RE.search(description):
            return "医生"
        if _OFFICER_HINT_RE.search(description):
            return "警探"
        if _PRIEST_HINT_RE.search(description):
            return "祭司"
        if _GUARD_HINT_RE.search(description):
            return "守卫"
        if female:
            return "陌生女性"
        if male:
            return "陌生男性"
        return "陌生人"

    if _DOCTOR_HINT_RE.search(description):
        return "doctor"
    if _OFFICER_HINT_RE.search(description):
        return "officer"
    if _PRIEST_HINT_RE.search(description):
        return "priest"
    if _GUARD_HINT_RE.search(description):
        return "guard"
    if female:
        return "unknown woman"
    if male:
        return "unknown man"
    return "unknown person"


def ensure_npc_visibility_fields(
    npc: dict[str, Any],
    *,
    default_revealed: bool = False,
) -> bool:
    """Populate ``name_revealed`` and ``player_known_name`` if missing.

    Returns True when the dict was mutated, so callers can decide whether
    to ``flag_modified`` the parent JSON column. Always idempotent — safe
    to call repeatedly.

    ``default_revealed`` controls the initial value of ``name_revealed``
    when not yet set. Use ``True`` for NPCs that come from the PC's own
    backstory (the player obviously knows their own ex-wife's name) and
    ``False`` for fresh-encounter NPCs.
    """
    if not isinstance(npc, dict):
        return False
    name = str(npc.get("name") or "").strip()
    if not name:
        return False

    changed = False
    if "name_revealed" not in npc:
        npc["name_revealed"] = bool(default_revealed)
        changed = True

    existing_label = str(npc.get("player_known_name") or "").strip()
    if not existing_label:
        if npc.get("name_revealed"):
            npc["player_known_name"] = name
        else:
            npc["player_known_name"] = derive_public_npc_name(npc) or name
        changed = True

    return changed


def reveal_name(npc: dict[str, Any]) -> bool:
    """Mark a previously-hidden NPC's name as known. Idempotent.

    The pre-reveal ``player_known_name`` (typically a description label
    such as "加油站老板") gets pushed into ``aliases`` before being
    overwritten by the true name. Otherwise a future ``[speak]<old
    label>[/speak]`` from the GM would not resolve back to this NPC and
    would spawn a stub ``npc_seen_*`` duplicate.
    """
    if not isinstance(npc, dict):
        return False
    if npc.get("name_revealed") is True:
        return False
    npc["name_revealed"] = True
    true_name = str(npc.get("name") or "").strip()
    old_label = str(npc.get("player_known_name") or "").strip()
    if old_label and old_label != true_name:
        aliases = npc.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        existing = {str(a).strip() for a in aliases if str(a).strip()}
        if old_label not in existing:
            aliases.append(old_label)
            npc["aliases"] = aliases
    npc["player_known_name"] = true_name or old_label
    return True


def mask_hidden_npc_names_in_text(
    text: str,
    npcs: list[dict[str, Any]] | None,
) -> tuple[str, list[str]]:
    """Substitute every hidden NPC's true name in ``text`` with its public
    label. Returns ``(masked_text, masked_npc_keys)``.

    Used to scrub module raw markdown / chapter prose before it lands in the
    GM prompt. Counterpart to ``mask_hidden_true_name`` for free-form text:
    a JSON dict can be field-overwritten, but module chapters are markdown
    paragraphs where names are sprinkled across stat blocks and narrative.

    Replacement order: longest true_name first, so that "Russ Patterson"
    is masked before "Russ" — otherwise the latter would consume the prefix
    and leave " Patterson" stranded.
    """
    if not text or not npcs:
        return text or "", []
    candidates: list[tuple[str, str, str]] = []
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if npc.get("name_revealed") is True:
            continue
        true_name = str(npc.get("name") or "").strip()
        public_label = str(npc.get("player_known_name") or "").strip()
        if not true_name or not public_label:
            continue
        if true_name == public_label or _same_identity_label(true_name, public_label):
            continue
        candidates.append((true_name, public_label, str(npc.get("key") or "")))

    if not candidates:
        return text, []

    candidates.sort(key=lambda triple: len(triple[0]), reverse=True)
    masked = text
    masked_keys: list[str] = []
    for true_name, public_label, key in candidates:
        if true_name in masked:
            masked = masked.replace(true_name, public_label)
            if key:
                masked_keys.append(key)
    return masked, masked_keys


def mask_hidden_true_name(npc: dict[str, Any]) -> bool:
    """Overwrite the ``name`` field with ``player_known_name`` when the player
    has not yet learned the NPC's real name. Mutates ``npc`` in place; returns
    True iff a substitution actually happened.

    Ported from chatlab's ``preprocess_helpers._mask_hidden_true_name``. The
    original chatlab comment explains the design choice — quoted here so the
    same lesson sticks in this codebase:

        Previously GM saw both ``name`` (true name) and ``player_known_name``
        (the label the player is allowed to see) with a prose rule saying
        "don't use name when hidden". LLMs routinely broke that rule — within
        a few turns the GM would slip into using the real name anyway.
        Turning the rule into a data invariant (GM literally cannot read the
        real name when it's hidden) removes the failure mode entirely.

    Always call this on a *copy* of the NPC dict before serialising into a
    GM-facing prompt. The original session.memory_state must keep the true
    name intact — only the wire payload to the LLM is masked.
    """
    if not isinstance(npc, dict):
        return False
    if npc.get("name_revealed") is True:
        return False
    public_label = str(npc.get("player_known_name") or "").strip()
    if not public_label:
        # No safe substitute yet (e.g. fresh-encounter NPC before
        # `ensure_npc_visibility_fields` has assigned a derived label). Leaving
        # `name` as-is is the lesser evil; the GM needs *something* to refer
        # to them by. Subsequent turns will mask once a label exists.
        return False
    true_name = str(npc.get("name") or "").strip()
    if not true_name or true_name == public_label:
        return False
    npc["name"] = public_label
    npc["_true_name_hidden"] = True
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _same_identity_label(a: str, b: str) -> bool:
    norm_a = _LABEL_NORMALISE_RE.sub("", str(a or "")).lower()
    norm_b = _LABEL_NORMALISE_RE.sub("", str(b or "")).lower()
    return bool(norm_a) and norm_a == norm_b
