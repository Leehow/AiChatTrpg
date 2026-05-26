from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ParsedModule(Base, TimestampMixin):
    """An adventure / module parsed out of an uploaded file.

    Visibility is per-row via `is_shared`:
      - is_shared=True  → listed for every signed-in user (the default
        for new uploads, matching the "small group of friends" install)
      - is_shared=False → visible only to the owner

    Only the owner can change `is_shared`, edit, or delete. Sessions
    reference modules by `id`, never by copying the markdown.
    """

    __tablename__ = "parsed_modules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # New uploads default to private; users explicitly opt into sharing.
    # Old rows migrated in via the schema bootstrap stay shared (their
    # column DEFAULT is 1) so we don't surprise anyone by yanking
    # already-visible modules.
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # LLM-cleaned display title (e.g. "血色公路" from "血色公路_v2_scan.pdf").
    # Generated on-demand by services.short_name.extract_module_title and
    # cached here so the room-name composer doesn't re-call the model.
    extracted_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_format: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    backend: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    toc: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    toc_source: Mapped[str] = mapped_column(String(16), nullable=False, default="heuristic")

    semantic_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    semantic_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    semantic_structure: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    semantic_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    briefing_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appendix_index: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
