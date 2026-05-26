"""Schemas for the per-session bond-NPC endpoints.

Bond NPCs are PC-known characters seeded from the PC card (ex-wife, old
partner, mentor, etc.) via ``services.character_intake``. The intake pass
gives them names, roles, and psychology, but their voice cards and rich
prose fields (description / personality / relationship_dynamic) only
land when the player explicitly asks for enrichment.

These models back ``POST /api/sessions/{session_id}/bond-npcs/enrich``;
voice selection / TTS lock state stays under the audio router.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.session import SessionDetail


class BondNpcEnrichRequest(BaseModel):
    """Request payload for the session-wide bond NPC enrichment trigger.

    - ``force=False`` (default): only NPCs that look unfinished are touched
      and existing non-empty fields are preserved.
    - ``force=True``: every ``from_bond`` NPC is re-enriched and existing
      profile fields can be overwritten by fresh LLM output.
    - ``limit`` caps how many eligible NPCs are processed in one call;
      ``None`` means no cap.
    """

    force: bool = False
    limit: int | None = Field(default=None, ge=1)


class BondNpcEnrichResponse(BaseModel):
    """Result of a bond NPC enrichment call.

    ``session`` carries the post-update detail so the frontend can refresh
    its NPC panel without a follow-up GET. The counts and key lists let
    the UI render a precise toast (n enriched, m skipped, errors).
    """

    session: SessionDetail
    eligible: int = 0
    enriched: int = 0
    skipped: int = 0
    enriched_npc_keys: list[str] = Field(default_factory=list)
    skipped_npc_keys: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
