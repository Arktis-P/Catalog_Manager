from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session, contains_eager

from app.models.character import Character
from app.models.series import Series
from app.services.prompt_service import build_generation_prompt


class ReviewService:
    def __init__(self, db: Session):
        self.db = db

    def list_appearance_reviews(
        self,
        *,
        series_tag: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Character], int]:
        query = (
            self.db.query(Character)
            .join(Character.series)
            .options(contains_eager(Character.series))
            .filter(Character.from_related.is_(True), Character.appearance_confirmed.is_(False))
        )

        if series_tag:
            query = query.filter(Series.series_tag == series_tag)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Character.character_tag.ilike(pattern),
                    Character.display_name.ilike(pattern),
                    Series.display_name.ilike(pattern),
                    Series.series_tag.ilike(pattern),
                )
            )

        total = query.order_by(None).count()
        items = (
            query.order_by(Series.post_count.desc(), Character.post_count.desc(), Character.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def get_character(self, character_id: int) -> Character | None:
        return (
            self.db.query(Character)
            .join(Character.series)
            .options(contains_eager(Character.series))
            .filter(Character.id == character_id)
            .first()
        )

    def confirm_appearance(self, character_id: int) -> Character:
        character = self.get_character(character_id)
        if not character:
            raise ValueError("Character not found")
        if not character.from_related:
            raise ValueError("Character has no collected appearance tags")
        if character.appearance_confirmed:
            return character

        character.generation_prompt = build_generation_prompt(character)
        character.appearance_confirmed = True
        if character.status == "needs_check":
            character.status = "confirmed"
        self.db.commit()
        self.db.refresh(character)
        return character

    def update_appearance_draft(
        self,
        character_id: int,
        *,
        multi_color_hair: str | None = None,
        hair_color: str | None = None,
        hair_shape: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
    ) -> Character:
        character = self.get_character(character_id)
        if not character:
            raise ValueError("Character not found")
        if character.appearance_confirmed:
            raise ValueError("Appearance tags are already confirmed")

        if multi_color_hair is not None:
            character.multi_color_hair = multi_color_hair or None
        if hair_color is not None:
            character.hair_color = hair_color or None
        if hair_shape is not None:
            character.hair_shape = hair_shape or None
        if eye_color is not None:
            character.eye_color = eye_color or None
        if feature_tags is not None:
            character.feature_tags = feature_tags or None

        character.generation_prompt = build_generation_prompt(character)
        self.db.commit()
        self.db.refresh(character)
        return character
