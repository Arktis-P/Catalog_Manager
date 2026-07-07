from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GlobalCharacter(Base):
    """Danbooru character-category tag, independent of any single Series.

    Related to Series through CharacterSeriesLink (many-to-many). Kept separate
    from the existing series-scoped `characters` table so the Series feature
    is unaffected.
    """

    __tablename__ = "global_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_tag: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # 통합 상태 (전체) + 세부 상태(외형/성별/시리즈) - 부분 실패를 개별 추적하기 위해 분리
    collect_status: Mapped[str] = mapped_column(String(50), nullable=False, default="uncollected", index=True)
    appearance_status: Mapped[str] = mapped_column(String(50), nullable=False, default="uncollected")
    gender_status: Mapped[str] = mapped_column(String(50), nullable=False, default="uncollected")
    series_status: Mapped[str] = mapped_column(String(50), nullable=False, default="uncollected")

    multi_color_hair: Mapped[str | None] = mapped_column(Text, nullable=True)
    hair_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    hair_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    eye_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # 의상 차이 등으로 태그가 분리된 동일 캐릭터를 묶기 위한 자기참조 부모 링크.
    # Series의 parent_series_id와 동일하게 1단계 깊이만 허용한다 (부모는 자식을 가질 수 없음).
    parent_character_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_characters.id", ondelete="SET NULL"), nullable=True, index=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    series_links = relationship(
        "CharacterSeriesLink",
        back_populates="character",
        cascade="all, delete-orphan",
        order_by="CharacterSeriesLink.relevance_rank",
    )
    images = relationship(
        "GlobalCharacterImage", back_populates="global_character", cascade="all, delete-orphan"
    )
    generation_jobs = relationship(
        "GlobalCharacterGenerationJob", back_populates="global_character", cascade="all, delete-orphan"
    )
    review = relationship(
        "GlobalCharacterReview", back_populates="global_character", uselist=False, cascade="all, delete-orphan"
    )
    parent = relationship(
        "GlobalCharacter", remote_side=[id], back_populates="children", foreign_keys=[parent_character_id]
    )
    children = relationship(
        "GlobalCharacter", back_populates="parent", foreign_keys=[parent_character_id]
    )
