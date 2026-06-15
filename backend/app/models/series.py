from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_tag: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    merged_moved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merged_duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_collect_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_collect_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_appearance_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    parent = relationship("Series", remote_side=[id], back_populates="children", foreign_keys=[parent_series_id])
    children = relationship("Series", back_populates="parent", foreign_keys=[parent_series_id])
    characters = relationship(
        "Character",
        back_populates="series",
        cascade="all, delete-orphan",
        foreign_keys="Character.series_id",
    )
    sourced_characters = relationship(
        "Character",
        foreign_keys="Character.source_series_id",
        viewonly=True,
    )
