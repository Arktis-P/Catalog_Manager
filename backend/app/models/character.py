from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("series_id", "character_tag", name="uq_characters_series_character"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    character_tag: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    danbooru_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    multi_color_hair: Mapped[str | None] = mapped_column(Text, nullable=True)
    hair_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    hair_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    eye_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="needs_check", index=True)
    from_wiki: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_list_page: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_posts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_check_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    series = relationship("Series", back_populates="characters")
    generation_jobs = relationship("GenerationJob", back_populates="character", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="character", cascade="all, delete-orphan")
    review = relationship("Review", back_populates="character", uselist=False, cascade="all, delete-orphan")
