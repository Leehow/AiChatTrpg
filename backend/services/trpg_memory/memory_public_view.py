"""Player-visible projection of memory.

Never expose raw memory tables directly to players. This service creates a
safe, filtered view for clue/relationship/recall panels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.trpg_context.models import Visibility
from .memory_models import MemoryItem, MemoryKind, MemoryStatus
from .memory_store import MemoryStore


@dataclass(frozen=True)
class PublicRelationship:
    npc_id: str
    summary: str
    confidence: float
    known_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicClue:
    clue_id: str | None
    title: str
    status: str
    points_to: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class PublicMemoryView:
    relationships: tuple[PublicRelationship, ...] = field(default_factory=tuple)
    clues: tuple[PublicClue, ...] = field(default_factory=tuple)
    open_threads: tuple[str, ...] = field(default_factory=tuple)
    remembered_facts: tuple[str, ...] = field(default_factory=tuple)


class MemoryPublicViewService:
    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    def build_for_party(self, *, campaign_id: str, party_id: str | None = None) -> PublicMemoryView:
        del party_id  # reserved for campaigns with multiple parties
        memories = self.memory_store.query(
            campaign_id=campaign_id,
            visibility=(Visibility.PUBLIC, Visibility.PARTY_KNOWN),
            include_inactive=False,
        )
        memories = tuple(item for item in memories if item.status == MemoryStatus.ACTIVE)
        relationships: list[PublicRelationship] = []
        clues: list[PublicClue] = []
        open_threads: list[str] = []
        facts: list[str] = []

        for item in memories:
            if item.kind == MemoryKind.RELATIONSHIP:
                relationships.append(self._relationship(item))
            elif item.kind == MemoryKind.CLUE:
                clues.append(self._clue(item))
            elif item.kind == MemoryKind.PLOT:
                open_threads.append(item.text)
            elif item.kind == MemoryKind.FACT:
                facts.append(item.text)

        return PublicMemoryView(
            relationships=tuple(relationships),
            clues=tuple(clues),
            open_threads=tuple(dict.fromkeys(open_threads)),
            remembered_facts=tuple(dict.fromkeys(facts)),
        )

    def _relationship(self, item: MemoryItem) -> PublicRelationship:
        npc_id = item.owner_id or next((sid for sid in item.subject_ids if sid.startswith("npc_")), "unknown_npc")
        reasons = tuple(str(reason) for reason in item.metadata.get("known_reasons", ()))
        return PublicRelationship(npc_id=npc_id, summary=item.text, confidence=item.confidence, known_reasons=reasons)

    def _clue(self, item: MemoryItem) -> PublicClue:
        clue_id = str(item.metadata.get("clue_id")) if item.metadata.get("clue_id") else None
        title = str(item.metadata.get("title") or item.text[:60])
        status = str(item.metadata.get("status") or "discovered")
        points_to = tuple(str(x) for x in item.metadata.get("points_to", ()))
        return PublicClue(clue_id=clue_id, title=title, status=status, points_to=points_to, summary=item.text)
