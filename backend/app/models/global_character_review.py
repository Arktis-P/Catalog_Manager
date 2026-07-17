from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GlobalCharacterReview(Base):
    """Review state for a GlobalCharacter. Mirrors `Review` (series-scoped)."""

    __tablename__ = "global_character_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    cover_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_character_images.id", ondelete="SET NULL"), nullable=True
    )
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    rating_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="primary")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    global_character = relationship("GlobalCharacter", back_populates="review")
