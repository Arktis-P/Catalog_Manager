from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CharacterLinkSuggestion(Base):
    """Durable parent/child grouping suggestion for a GlobalCharacter pair.

    One row per (parent_character_id, child_character_id) pair, regardless of
    status. Recalculation upserts pending rows and preserves any row already
    decided by a user (accepted/rejected) -- see
    `character_group_service.recalculate_group`.
    """

    __tablename__ = "character_link_suggestions"
    __table_args__ = (
        UniqueConstraint("parent_character_id", "child_character_id", name="uq_char_link_suggestion_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # pending | accepted | rejected | superseded
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    parent = relationship("GlobalCharacter", foreign_keys=[parent_character_id])
    child = relationship("GlobalCharacter", foreign_keys=[child_character_id])
