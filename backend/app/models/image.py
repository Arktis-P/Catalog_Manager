from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    auto_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    hair_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eye_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gender_pred: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cover_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    character = relationship("Character", back_populates="images")
    generation_job = relationship("GenerationJob", back_populates="images")
