"""Equipment param enrichment: map PC card weapons / armor / items to
ruleset `parameter_families` entries via one LLM batch call, merge canonical
mechanical fields back onto the PC.

Ports the *intent* of chatlab's `equipment_param_enricher.py` (550 lines)
in ~250 lines. The chatlab version does the same thing — collects every
unenriched weapon/armor/item on the card, asks an LLM to map each to a
canonical ruleset entry name (e.g. `折刀` → `Knife, Small`), then merges
the entry's `damage` / `impaling` / `base_range` / `malfunction` etc into
the PC's slot WITHOUT overwriting fields the chargen LLM already filled.

Why we need this on top of Wave 3 `[SEARCH_RULES]`:
- Wave 3 lets the GM pull a weapon entry on demand, but it's another
  round-trip per [CONTEST]. Pre-enrichment puts those fields on the PC
  card up front so the GM can write `attacker_impaling=true` in the same
  turn it emits `[CONTEST]`.
- chargen LLM populates `damage`, `range`, `attacks` etc. but rarely
  populates `impaling` (CoC 7e's most consequential combat flag — extreme
  / critical hits with impaling weapons reroll damage and add the max
  weapon roll). Without `impaling`, every knife / spear contest under-
  computes its top-tier damage.

Run order:
- One-shot, idempotent. Stamps `character.equipment_enriched_at` on
  success so a re-run is a no-op until equipment changes.
- Triggered explicitly via the new `enrich_pc_equipment` endpoint OR
  hooked into `character-confirm` so the first IC turn already has clean
  weapon stats. Not auto-fired in `stream_ic_turn` to keep IC turn
  latency predictable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from llm import ChatMessage as LlmChatMessage
from llm import build_client
from orm.models import GameSession, Ruleset
from services.character_creator import _resolve_model

logger = logging.getLogger("chatrpg.trpg")


# Field families per equipment bucket. The "must-have" fields determine
# whether a slot is considered "already enriched"; if at least
# `_MIN_FIELDS_PRESENT[bucket]` of these are populated AND `impaling` is set
# (when applicable), we skip that slot.
_WEAPON_CANONICAL_FIELDS = {
    "damage", "range", "base_range", "attacks", "ammo",
    "malfunction", "impaling", "skill", "skill_name",
    "category", "weapon_category",
}
_ARMOR_CANONICAL_FIELDS = {
    "armor_points", "armor_value", "protection", "category",
}
_ITEM_CANONICAL_FIELDS = {
    "effect", "category", "charges_or_capacity", "cost_modern",
    "cost_1920s", "damage", "range", "armor_points",
}
_BUCKET_CANONICAL: dict[str, set[str]] = {
    "weapons": _WEAPON_CANONICAL_FIELDS,
    "armor": _ARMOR_CANONICAL_FIELDS,
    "items": _ITEM_CANONICAL_FIELDS,
    "accessories": _ITEM_CANONICAL_FIELDS,
}
_BUCKET_TO_FAMILY: dict[str, str] = {
    "weapons": "weapon",
    "armor": "armor",
    "items": "item",
    "accessories": "item",
}

_MAX_CANDIDATES_PER_BUCKET = 60   # how many ruleset entries we ship as candidates
_MAX_TARGET_NAME_CHARS = 80
_MAX_TARGET_NOTE_CHARS = 120


_MATCH_PROMPT = """You map localized TRPG equipment names to canonical ruleset entries.

This is a cross-language matching task. PC card entries are often in the player's chosen language (Chinese, Japanese, etc.) while ruleset entries are in the ruleset's original language (often English). Use the candidate `hint` field — which carries aliases, category, and a short description — to find the closest physical-object match.

Rules:
- Return STRICT JSON only. No markdown fences, no commentary.
- Choose ONLY from the provided candidate entry `name` strings (case + punctuation exact). If none of the candidates plausibly matches, return null for that target id.
- Prefer the closest official rules entry for the SAME physical object. `折刀` (folding knife / switchblade) → `Knife, Small`. `撬胎棒` (tire iron / crowbar-like) → `Crowbar` if present, else `Club, Small` etc. `.38左轮手枪` → `Revolver, .38` or whatever revolver entry the candidates list.
- Read each candidate's `hint`: `aliases: [...]` is the most reliable cross-language signal — a Chinese knife matching a candidate whose aliases include `switchblade` is a strong match.
- Do NOT invent new names. Do NOT mix buckets (weapon target gets a weapon candidate).

Targets (PC equipment items needing canonical lookup):
{targets_json}

Candidates per bucket (slug → list of `{{name, hint}}`):
{candidates_json}

Return JSON exactly:
{{"matches": {{"<target id>": {{"slug": "weapon", "name": "Knife, Small"}}, "<other id>": null}}}}
"""


@dataclass
class EnrichmentResult:
    enriched_count: int = 0
    skipped_count: int = 0
    no_match_count: int = 0
    errors: list[str] = field(default_factory=list)
    by_bucket: dict[str, int] = field(default_factory=dict)
    skipped_reason: str = ""


# ---------------------------------------------------------------------------
# Card walking


def _is_empty(v: Any) -> bool:
    return v in (None, "", [], {}, "-")


def _entry_name(entry: dict[str, Any]) -> str:
    for key in ("name", "title", "label", "english_name", "canonical_name"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _entry_already_enriched(bucket: str, entry: dict[str, Any]) -> bool:
    """A slot is "enriched enough" when most canonical fields are already
    populated AND `impaling` is set (for weapons). chargen LLM usually
    fills damage/range/attacks but skips `impaling` — that flag alone is
    the deciding factor for most weapons."""
    canonical = _BUCKET_CANONICAL.get(bucket, _ITEM_CANONICAL_FIELDS)
    present = sum(1 for k in canonical if not _is_empty(entry.get(k)))
    if bucket == "weapons":
        return present >= 4 and "impaling" in entry
    if bucket == "armor":
        return present >= 2
    return present >= 2


def _iter_pc_equipment(card: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """Return [(bucket, items_list_ref), ...] so callers can mutate in place."""
    out: list[tuple[str, list[Any]]] = []
    eq = card.get("equipment")
    if isinstance(eq, dict):
        for key, value in eq.items():
            if isinstance(value, list) and key in _BUCKET_CANONICAL:
                out.append((key, value))
    elif isinstance(eq, list):
        out.append(("items", eq))
    return out


# ---------------------------------------------------------------------------
# Ruleset candidate index


def _ruleset_family_entries(parsed_v6: dict[str, Any], family_id: str) -> list[dict[str, Any]]:
    fams = parsed_v6.get("parameter_families")
    if not isinstance(fams, list):
        return []
    for fam in fams:
        if not isinstance(fam, dict):
            continue
        if str(fam.get("family_id") or "").strip() != family_id:
            continue
        blob = fam.get("json")
        if isinstance(blob, list):
            return [e for e in blob if isinstance(e, dict)]
        if isinstance(blob, dict):
            for k in ("entries", "items", "options", "rows", "values"):
                nested = blob.get(k)
                if isinstance(nested, list):
                    return [e for e in nested if isinstance(e, dict)]
            # dict-of-dicts: turn keys into ids
            return [
                {**v, "id": k} for k, v in blob.items() if isinstance(v, dict)
            ]
    return []


def _candidate_hint(entry: dict[str, Any]) -> str:
    """Pull a tiny disambiguation hint from a candidate so the LLM can
    cross-language match (e.g. PC `折刀` ↔ ruleset `Knife, Small` whose
    aliases list contains `switchblade`)."""
    bits: list[str] = []
    aliases = entry.get("aliases")
    if isinstance(aliases, list):
        flat = ", ".join(str(a) for a in aliases if str(a).strip())
        if flat:
            bits.append(f"aliases: {flat}")
    cat = entry.get("category") or entry.get("weapon_category")
    if isinstance(cat, str) and cat.strip():
        bits.append(f"category: {cat.strip()}")
    desc = entry.get("description") or entry.get("notes") or entry.get("effect")
    if isinstance(desc, str) and desc.strip():
        bits.append(desc.strip()[:80])
    return " | ".join(bits)


def _build_candidates(parsed_v6: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """For each bucket → list of `{name, hint}` candidate dicts (capped).

    Hints carry aliases + category + short description so the LLM can match
    across languages even when the PC card is localized (`折刀`) but the
    ruleset entries are English-original (`Knife, Small`)."""
    candidates: dict[str, list[dict[str, str]]] = {}
    for bucket, family_id in _BUCKET_TO_FAMILY.items():
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for e in _ruleset_family_entries(parsed_v6, family_id):
            n = _entry_name(e)
            if not n or n in seen:
                continue
            seen.add(n)
            rows.append({"name": n, "hint": _candidate_hint(e)})
            if len(rows) >= _MAX_CANDIDATES_PER_BUCKET:
                break
        if rows:
            candidates[bucket] = rows
    return candidates


def _ruleset_entry_by_name(
    parsed_v6: dict[str, Any], family_id: str, name: str,
) -> dict[str, Any] | None:
    """Locate a family entry by canonical name (exact / case-insensitive)."""
    target = (name or "").strip().lower()
    if not target:
        return None
    for e in _ruleset_family_entries(parsed_v6, family_id):
        if _entry_name(e).lower() == target:
            return e
    return None


# ---------------------------------------------------------------------------
# Merge canonical fields onto PC entry


_NEVER_OVERWRITE_FIELDS = {"name", "notes", "description", "skill_name"}


def _merge_canonical(
    bucket: str, pc_entry: dict[str, Any], canonical: dict[str, Any],
) -> int:
    """Copy canonical fields onto pc_entry. Returns count of fields actually
    written. Existing non-empty fields are NEVER overwritten — chargen
    output wins because it knows the in-fiction context (e.g. damage with a
    house rule). impaling and other boolean flags ARE filled even when
    absent on PC because chargen rarely sets them."""
    relevant = _BUCKET_CANONICAL.get(bucket, _ITEM_CANONICAL_FIELDS)
    written = 0
    for k, v in canonical.items():
        if k in _NEVER_OVERWRITE_FIELDS:
            continue
        if k not in relevant and k != "impaling" and k != "aliases":
            continue
        if v is None or v == "":
            continue
        if not _is_empty(pc_entry.get(k)):
            continue
        pc_entry[k] = v
        written += 1
    # Tag with provenance so a future run can tell what was injected vs
    # chargen-original.
    if written:
        existing = pc_entry.get("_enrichment_source")
        if not isinstance(existing, list):
            existing = []
        existing.append({
            "matched": _entry_name(canonical),
            "at": datetime.now(timezone.utc).isoformat(),
            "fields": [k for k in canonical if k in _BUCKET_CANONICAL.get(bucket, set())],
        })
        pc_entry["_enrichment_source"] = existing
    return written


# ---------------------------------------------------------------------------
# LLM batch matching


def _strip_json_fence(text: str) -> str:
    """Strip ```json ... ``` fences if the model wrapped its reply."""
    s = text.strip()
    if s.startswith("```"):
        # peel first fence line
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _parse_match_json(raw: str) -> dict[str, Any]:
    s = _strip_json_fence(raw)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Best-effort: find the first {...} block
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    if not isinstance(obj, dict):
        return {}
    matches = obj.get("matches")
    return matches if isinstance(matches, dict) else {}


async def _llm_batch_match(
    db: AsyncSession,
    targets: list[dict[str, Any]],
    candidates: dict[str, list[str]],
) -> dict[str, dict[str, str] | None]:
    """One LLM call → name mapping. Returns {target_id: {slug, name} | None}."""
    if not targets or not candidates:
        return {}
    prompt = _MATCH_PROMPT.format(
        targets_json=json.dumps(targets, ensure_ascii=False, indent=2),
        candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
    )
    provider, model_name, api_key, base_url = await _resolve_model(db)
    client = build_client(provider, model_name, api_key, base_url)
    chunks: list[str] = []
    async for chunk in client.stream_chat(
        [LlmChatMessage(role="user", content=prompt)],
        temperature=0.0,
    ):
        if chunk.delta:
            chunks.append(chunk.delta)
    raw = "".join(chunks)
    return _parse_match_json(raw)


# ---------------------------------------------------------------------------
# Public entrypoint


async def enrich_pc_equipment(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    *,
    force: bool = False,
) -> EnrichmentResult:
    """Walk PC equipment, ask the LLM to map each unenriched slot to a
    ruleset family entry, merge canonical fields. Idempotent unless `force`
    is set or equipment slots have changed since the last enrichment."""
    result = EnrichmentResult()
    pc = session.character if isinstance(session.character, dict) else {}
    if not pc:
        result.skipped_reason = "no_pc_card"
        return result
    parsed_v6 = ruleset.parsed_v6 if isinstance(getattr(ruleset, "parsed_v6", None), dict) else {}
    if not parsed_v6:
        result.skipped_reason = "no_parsed_v6"
        return result

    # Build per-bucket candidate lists once.
    candidates = _build_candidates(parsed_v6)
    if not candidates:
        result.skipped_reason = "no_parameter_families"
        return result

    # Collect targets across all buckets.
    targets: list[dict[str, Any]] = []
    target_index: dict[str, tuple[str, dict[str, Any]]] = {}  # tid → (bucket, pc_entry)
    for bucket, items in _iter_pc_equipment(pc):
        if bucket not in candidates:
            continue
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                continue
            name = _entry_name(raw)
            if not name:
                continue
            if not force and _entry_already_enriched(bucket, raw):
                result.skipped_count += 1
                continue
            tid = f"{bucket}.{idx}"
            note = str(raw.get("notes") or raw.get("description") or "").strip()
            targets.append({
                "id": tid,
                "bucket": bucket,
                "name": name[:_MAX_TARGET_NAME_CHARS],
                "note": note[:_MAX_TARGET_NOTE_CHARS],
            })
            target_index[tid] = (bucket, raw)

    if not targets:
        result.skipped_reason = "all_already_enriched"
        return result

    try:
        matches = await _llm_batch_match(db, targets, candidates)
    except Exception as exc:
        logger.warning("[enricher] llm batch match failed: %s", exc, exc_info=True)
        result.errors.append(f"llm_failed: {type(exc).__name__}: {exc}")
        result.skipped_reason = "llm_failed"
        return result

    for tid, (bucket, pc_entry) in target_index.items():
        match = matches.get(tid)
        if not isinstance(match, dict):
            result.no_match_count += 1
            continue
        slug = str(match.get("slug") or "").strip().lower()
        canonical_name = str(match.get("name") or "").strip()
        if not canonical_name:
            result.no_match_count += 1
            continue
        family_id = _BUCKET_TO_FAMILY.get(bucket)
        if not family_id:
            result.no_match_count += 1
            continue
        # Cross-check the slug — if the LLM returned a different bucket for
        # this target, treat as no-match.
        if slug and slug != family_id and slug != bucket:
            logger.info(
                "[enricher] target=%s bucket=%s LLM picked slug=%s — skipping",
                tid, bucket, slug,
            )
            result.no_match_count += 1
            continue
        canonical = _ruleset_entry_by_name(parsed_v6, family_id, canonical_name)
        if canonical is None:
            result.no_match_count += 1
            continue
        wrote = _merge_canonical(bucket, pc_entry, canonical)
        if wrote:
            result.enriched_count += 1
            result.by_bucket[bucket] = result.by_bucket.get(bucket, 0) + 1

    if result.enriched_count == 0:
        # Nothing landed (LLM matched but our entries already had every
        # field, or all matches failed cross-checks). Skip the commit.
        return result

    # Stamp + commit.
    pc["equipment_enriched_at"] = datetime.now(timezone.utc).isoformat()
    session.character = pc
    flag_modified(session, "character")
    await db.commit()
    return result
