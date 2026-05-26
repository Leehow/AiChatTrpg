from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ModelPoolEntry(Base, TimestampMixin):
    """User-curated (provider, model) pair.

    Independent role flags coexist; exactly one row holds each flag at a
    time (or zero if the pool is empty), and a single row may hold any
    combination. `position` gives a stable display order independent of
    insertion timestamps.

    Roles:
      - `is_default`: main GM model (dice-IR compiler, GM sessions).
      - `is_fast`: cheap/low-latency model (intent classify, scene detect).
      - `is_dialogue`: NPC character dialogue model (separate from GM).
      - `is_avatar`: avatar image generation.
      - `is_illustration`: in-scene illustration image generation.
      - `is_narration`: narration TTS voice model.
    The image/TTS roles currently share the LLM provider list — concrete
    image/TTS provider catalogs are not wired yet (NoOp adapters).
    """

    __tablename__ = "model_pool_entries"
    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_pool_provider_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_fast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_dialogue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_avatar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_illustration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_narration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
