from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CharacterSeriesLink(Base):
    """Many-to-many link between a GlobalCharacter and a Series (by copyright tag).

    `series_id` may be null if the copyright tag could not be resolved to an
    existing/created Series row yet; `copyright_tag` always holds the raw tag text.
    """

    __tablename__ = "character_series_links"
    __table_args__ = (
        UniqueConstraint("global_character_id", "copyright_tag", name="uq_char_series_link_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_character_id: Mapped[int] = mapped_column(
        ForeignKey("global_characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    copyright_tag: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    relevance_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    character = relationship("GlobalCharacter", back_populates="series_links")
    series = relationship("Series")
