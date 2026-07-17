from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GlobalCharacterImage(Base):
    """Image generated for a GlobalCharacter (character-catalog centric generation).

    Mirrors `Image` but keyed to `global_characters` instead of the series-scoped
    `characters` table, so the Series-based generation/review feature is unaffected.
    """

    __tablename__ = "global_character_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_character_generation_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    auto_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    hair_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eye_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gender_pred: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cover_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality_checker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identity_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    character_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    hair_color_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    conflicting_character_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conflicting_character_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    identity_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_multicolor_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    identity_checker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    global_character = relationship("GlobalCharacter", back_populates="images")
    generation_job = relationship("GlobalCharacterGenerationJob", back_populates="images")
