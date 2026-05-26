from typing import Any

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Ruleset(Base, TimestampMixin):
    """A parsed v6 ruleset, kept whole alongside any compiled dice IR.

    `parsed_v6` is the full v6 JSON artifact as uploaded — we keep it intact
    so the four sections (core / scenarios / parameters / character_sheet)
    can be re-derived without re-uploading. `dice_ir` holds the compiler
    artifact (compiled IRs + validation metadata) once it's been produced;
    `check_spec` holds the single applied procedure used at game time.

    Visibility mirrors `parsed_modules`: `is_shared=False` is owner-only,
    `is_shared=True` is visible to every signed-in user. Only the owner can
    flip the flag, edit, or delete.
    """

    __tablename__ = "rulesets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    book_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    book_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    world_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # LLM-generated short tag (e.g. "coc", "dnd", "pf2e") shown in the room
    # list as `[coc]<module>`. Cached on first request; null until then.
    short_name: Mapped[str | None] = mapped_column(String(16), nullable=True)

    parsed_v6: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dice_ir: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    check_spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # LLM-compiled character UI schema (widget tree). Same compiling/failed
    # stub pattern as `dice_ir` so the frontend can render an in-flight state.
    character_ui: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
