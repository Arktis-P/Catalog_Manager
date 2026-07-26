from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ParentChildCandidateDismissal(Base):
    __tablename__ = "parent_child_candidate_dismissals"
    __table_args__ = (
        UniqueConstraint("parent_character_id", "candidate_character_id", name="uq_parent_child_candidate_dismissal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
