from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CharacterAppearanceTagRelevance(Base):
    """Appearance tag relevance collected for a GlobalCharacter."""

    __tablename__ = "character_appearance_tag_relevance"
    __table_args__ = (
        UniqueConstraint("global_character_id", "tag", name="uq_character_appearance_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    tag_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cooccurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    character_post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_prompt_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    global_character = relationship("GlobalCharacter", back_populates="appearance_relevances")
