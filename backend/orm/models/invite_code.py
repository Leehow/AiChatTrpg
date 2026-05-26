from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class InviteCode(Base, TimestampMixin):
    """Registration invite tracked by hash, never by raw code."""

    __tablename__ = "invite_codes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
