"""Idempotency and reinforcement keys for TRPG memories.

V2 used ``source_turn_ids`` in every idempotency basis. That made long-running
sessions accumulate copies of the same durable fact whenever it was mentioned
again. V3 splits identity into two scopes:

* EVENT: turn-scoped timeline entries; source turn/event participates in key.
* DURABLE_FACT: canonical facts, clues, beliefs, relationships, and plot hooks;
  source turn is evidence, not identity, so repeats reinforce the same memory.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from .memory_models import MemoryIdentityScope, MemoryKind, MemoryProposal

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\u2000-\u206f\u2e00-\u2e7f\'!\"#$%&()*+,\-./:;<=>?@\[\\\]^_`{|}~。！？；：，、（）【】《》〈〉「」『』·…—]+")


def normalize_memory_text(text: str) -> str:
    """Canonicalize memory text for durable identity."""

    value = unicodedata.normalize("NFKC", str(text or "")).casefold().strip()
    value = _PUNCT_RE.sub(" ", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value[:600]


def infer_identity_scope(proposal: MemoryProposal) -> MemoryIdentityScope:
    if proposal.identity_scope is not None:
        return proposal.identity_scope
    if proposal.kind == MemoryKind.PLOT and "event" in set(proposal.tags):
        return MemoryIdentityScope.EVENT
    return MemoryIdentityScope.DURABLE_FACT


def proposal_identity_basis(proposal: MemoryProposal) -> str:
    subject = ",".join(sorted(str(s) for s in proposal.subject_ids if str(s)))
    owner = proposal.owner_id or "none"
    visibility = proposal.visibility.value
    kind = proposal.kind.value
    text = normalize_memory_text(proposal.text)
    scope = infer_identity_scope(proposal)
    if scope == MemoryIdentityScope.EVENT:
        turns = ",".join(sorted(str(t) for t in proposal.source_turn_ids if str(t)))
        events = ",".join(sorted(str(e) for e in proposal.source_event_ids if str(e)))
        return f"{scope.value}|{kind}|{owner}|{visibility}|{subject}|{turns}|{events}|{text}"
    return f"{scope.value}|{kind}|{owner}|{visibility}|{subject}|{text}"


def stable_idempotency_key(campaign_id: str, proposal: MemoryProposal) -> str:
    basis = proposal_identity_basis(proposal)
    return hashlib.sha256(f"{campaign_id}|{basis}".encode("utf-8")).hexdigest()


def stable_memory_id_from_key(campaign_id: str, idempotency_key: str) -> str:
    return "mem_" + hashlib.sha256(f"{campaign_id}:{idempotency_key}".encode("utf-8")).hexdigest()[:24]
