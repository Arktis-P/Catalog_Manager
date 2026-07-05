from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GlobalCharacterGenerationJob(Base):
    """Generation job for a GlobalCharacter. Mirrors `GenerationJob` (series-scoped)."""

    __tablename__ = "global_character_generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    global_character = relationship("GlobalCharacter", back_populates="generation_jobs")
    images = relationship("GlobalCharacterImage", back_populates="generation_job")
