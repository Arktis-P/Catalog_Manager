from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.services.character_image_service import purge_character_images
from app.services.db_write_queue import commit_db_session
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
        commit_db_session(self.db)
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
        gender: str | None = None,
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
        if gender is not None:
            character.gender = gender or None

        character.generation_prompt = build_generation_prompt(character)
        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    @staticmethod
    def build_wiki_url(character_tag: str) -> str:
        return f"{settings.danbooru_base_url}/wiki_pages/{quote(character_tag)}"

    def _character_has_images(self):
        return exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.is_rejected.is_(False),
            )
        )

    def _character_has_cover(self):
        return exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.is_cover.is_(True),
            )
        )

    def list_catalog_reviews(
        self,
        *,
        series_id: int,
        filter_status: str = "pending",
        search: str | None = None,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[Series, list[Character], int]:
        series = self.db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise ValueError("Series not found")

        query = (
            self.db.query(Character)
            .join(Character.series)
            .outerjoin(Character.review)
            .options(
                contains_eager(Character.series),
                joinedload(Character.images),
                joinedload(Character.review),
            )
            .filter(Character.series_id == series_id)
            .filter(self._character_has_images())
        )

        if filter_status == "pending":
            query = query.filter(
                or_(
                    Review.id.is_(None),
                    Review.review_status != "completed",
                    ~self._character_has_cover(),
                )
            )
        elif filter_status == "completed":
            query = query.filter(Review.review_status == "completed")
        elif filter_status == "needs_check":
            query = query.filter(Character.status == "needs_check")

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Character.character_tag.ilike(pattern),
                    Character.display_name.ilike(pattern),
                )
            )

        total = query.order_by(None).count()
        items = (
            query.order_by(Character.post_count.desc(), Character.character_tag.asc(), Character.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return series, items, total

    def complete_catalog_review(
        self,
        character_id: int,
        *,
        cover_image_id: int | None = None,
        gender: str | None = None,
        rating: int | None = None,
        final_prompt: str | None = None,
    ) -> Character:
        character = (
            self.db.query(Character)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(Character.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")

        review = character.review
        if not review:
            review = Review(character_id=character.id)
            self.db.add(review)
            character.review = review

        normalized_gender = normalize_gender(gender) if gender else None
        if not normalized_gender and character.gender:
            normalized_gender = normalize_gender(character.gender)
        if normalized_gender:
            character.gender = normalized_gender
            review.gender = normalized_gender

        if rating == 0:
            purge_character_images(self.db, character)
            review.cover_image_id = None
        else:
            if not cover_image_id:
                raise ValueError("Cover image is required unless rating is 0")

            cover_image = next(
                (image for image in character.images if image.id == cover_image_id and not image.is_rejected),
                None,
            )
            if not cover_image:
                raise ValueError("Cover image not found or rejected")

            review.cover_image_id = cover_image_id
            for image in character.images:
                image.is_cover = image.id == cover_image_id

        review.rating = rating
        review.final_prompt = final_prompt or character.generation_prompt
        review.review_status = "completed"

        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def dismiss_needs_check(self, character_id: int) -> Character:
        character = (
            self.db.query(Character)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(Character.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")
        if character.status != "needs_check":
            raise ValueError("Character is not marked needs_check")

        character.status = "confirmed"
        character.needs_check_reason = None
        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def regenerate_catalog_images(
        self,
        character_id: int,
        *,
        prompt: str,
        gender: str | None = None,
    ):
        from app.services.review_regenerate_job_manager import review_regenerate_job_manager

        return review_regenerate_job_manager.enqueue(
            character_id,
            prompt=prompt,
            gender=gender,
        )

    def undo_catalog_review(self, character_id: int) -> Character:
        character = (
            self.db.query(Character)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(Character.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")
        if not character.review or character.review.review_status != "completed":
            raise ValueError("No completed review to undo")

        character.review.review_status = "pending"
        character.review.cover_image_id = None
        for image in character.images:
            image.is_cover = False

        commit_db_session(self.db)
        self.db.refresh(character)
        return character
