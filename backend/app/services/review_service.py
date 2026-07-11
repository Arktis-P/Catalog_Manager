from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.services.character_image_service import (
    move_image_to_catalog_folder,
    purge_character_images,
    purge_global_character_images,
    purge_noncover_images,
    purge_noncover_images_global,
)
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

        _pending_condition = or_(
            Review.id.is_(None),
            Review.review_status != "completed",
            ~self._character_has_cover(),
        )
        _pass_img_exists = exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.auto_status == "pass",
                Image.is_rejected.is_(False),
            )
        )
        _non_reject_img_exists = exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.auto_status != "reject_candidate",
                Image.is_rejected.is_(False),
            )
        )
        if filter_status == "pending":
            query = query.filter(_pending_condition)
        elif filter_status == "completed":
            query = query.filter(Review.review_status == "completed")
        elif filter_status == "needs_check":
            query = query.filter(Character.status == "needs_check")
        elif filter_status == "triage_fast":
            # WD pass 이미지가 하나라도 있고 아직 미완료
            query = query.filter(_pending_condition, _pass_img_exists)
        elif filter_status == "triage_check":
            # 비-reject 이미지는 있지만 pass 이미지가 없음 + 미완료
            query = query.filter(_pending_condition, _non_reject_img_exists, ~_pass_img_exists)
        elif filter_status == "triage_regen":
            # 모든 이미지가 reject_candidate (비-reject 없음) + 미완료
            query = query.filter(_pending_condition, ~_non_reject_img_exists)

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
        selected_tags: str | None = None,
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

        if rating in (0, -1):
            if rating == 0:
                # -1점은 카탈로그에 노출되지 않지만 이미지는 삭제하지 않는다. 0점만
                # "생성 실패/사용 불가"로 간주해 이미지를 완전히 삭제한다.
                purge_character_images(self.db, character)
            review.cover_image_id = None
        else:
            if not cover_image_id:
                raise ValueError("Cover image is required unless rating is 0 or -1")

            cover_image = next(
                (image for image in character.images if image.id == cover_image_id and not image.is_rejected),
                None,
            )
            if not cover_image:
                raise ValueError("Cover image not found or rejected")

            review.cover_image_id = cover_image_id
            for image in character.images:
                image.is_cover = image.id == cover_image_id
            move_image_to_catalog_folder(self.db, cover_image)

        review.rating = rating
        # 0/-1점은 카탈로그에 이미지 없이 성별+기본 태그만 노출되어야 하므로,
        # 검수 화면에서 선택 반영된 프롬프트/태그가 아니라 항상 기본 프롬프트를 저장한다.
        review.final_prompt = character.generation_prompt if rating in (0, -1) else (final_prompt or character.generation_prompt)
        review.selected_tags = None if rating in (0, -1) else (selected_tags or None)
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

    def regenerate_catalog_images_global(
        self,
        global_character_id: int,
        *,
        prompt: str,
        gender: str | None = None,
    ):
        from app.services.review_regenerate_job_manager import review_regenerate_job_manager

        return review_regenerate_job_manager.enqueue_global(
            global_character_id,
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

    # ── 캐릭터 목록(GlobalCharacter) 중심 리뷰 ──────────────────────────
    # 시리즈 중심 Catalog Review와 완전히 독립적으로 GlobalCharacter*_ 테이블만 사용한다.

    def _global_character_has_images(self):
        return exists(
            select(1).where(
                GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                GlobalCharacterImage.is_rejected.is_(False),
            )
        )

    def list_catalog_reviews_global(
        self,
        *,
        filter_status: str = "pending",
        search: str | None = None,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[list[GlobalCharacter], int]:
        query = (
            self.db.query(GlobalCharacter)
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .options(
                joinedload(GlobalCharacter.images),
                joinedload(GlobalCharacter.review),
                joinedload(GlobalCharacter.parent),
                selectinload(GlobalCharacter.children),
            )
            .filter(self._global_character_has_images())
        )

        if filter_status == "pending":
            query = query.filter(
                or_(GlobalCharacterReview.id.is_(None), GlobalCharacterReview.review_status != "completed")
            )
        elif filter_status == "completed":
            query = query.filter(GlobalCharacterReview.review_status == "completed")

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(GlobalCharacter.character_tag.ilike(pattern), GlobalCharacter.display_name.ilike(pattern))
            )

        total = query.order_by(None).count()
        items = (
            query.order_by(
                GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc()
            )
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def complete_catalog_review_global(
        self,
        global_character_id: int,
        *,
        cover_image_id: int | None = None,
        gender: str | None = None,
        rating: int | None = None,
        final_prompt: str | None = None,
        selected_tags: str | None = None,
    ) -> GlobalCharacter:
        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == global_character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")

        review = character.review
        if not review:
            review = GlobalCharacterReview(global_character_id=character.id)
            self.db.add(review)
            character.review = review

        normalized_gender = normalize_gender(gender) if gender else None
        if not normalized_gender and character.gender:
            normalized_gender = normalize_gender(character.gender)
        if normalized_gender:
            review.gender = normalized_gender

        if rating in (0, -1):
            if rating == 0:
                purge_global_character_images(self.db, character)
            review.cover_image_id = None
        else:
            if not cover_image_id:
                raise ValueError("Cover image is required unless rating is 0 or -1")

            cover_image = next(
                (image for image in character.images if image.id == cover_image_id and not image.is_rejected),
                None,
            )
            if not cover_image:
                raise ValueError("Cover image not found or rejected")

            review.cover_image_id = cover_image_id
            for image in character.images:
                image.is_cover = image.id == cover_image_id
            move_image_to_catalog_folder(self.db, cover_image)

        review.rating = rating
        base_prompt = getattr(character, "generation_prompt", None)
        # 0/-1점은 카탈로그에 이미지 없이 성별+기본 태그만 노출되어야 하므로,
        # 검수 화면에서 선택 반영된 프롬프트/태그가 아니라 항상 기본 프롬프트를 저장한다.
        review.final_prompt = base_prompt if rating in (0, -1) else (final_prompt or base_prompt)
        review.selected_tags = None if rating in (0, -1) else (selected_tags or None)
        review.review_status = "completed"

        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def purge_unselected_images(self, character_id: int) -> tuple[Character, int]:
        """완료된 리뷰에서 커버로 선택되지 않은 이미지를 파일까지 완전히 삭제한다.
        사용자가 명시적으로 버튼을 눌렀을 때만 호출되는 되돌릴 수 없는 동작."""
        character = (
            self.db.query(Character)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(Character.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")
        if not character.review or character.review.review_status != "completed":
            raise ValueError("완료된 리뷰가 아닙니다")
        if not character.review.cover_image_id and character.review.rating not in (-1, 0):
            raise ValueError("선택된 커버 이미지가 없습니다")

        removed = purge_noncover_images(self.db, character)
        commit_db_session(self.db)
        self.db.refresh(character)
        return character, removed

    def purge_unselected_images_bulk(self, series_id: int, *, search: str | None = None) -> tuple[int, int]:
        """완료된 리뷰 전체(현재 페이지 제한 없이)에서 미선택 이미지를 일괄 삭제한다."""
        query = (
            self.db.query(Character)
            .join(Character.review)
            .filter(Character.series_id == series_id, Review.review_status == "completed")
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(Character.character_tag.ilike(pattern), Character.display_name.ilike(pattern))
            )
        character_ids = [row[0] for row in query.with_entities(Character.id).all()]

        affected = 0
        removed_total = 0
        for character_id in character_ids:
            try:
                _, removed = self.purge_unselected_images(character_id)
            except ValueError:
                continue
            if removed:
                affected += 1
                removed_total += removed
        return affected, removed_total

    def undo_catalog_review_global(self, global_character_id: int) -> GlobalCharacter:
        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == global_character_id)
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

    def purge_unselected_images_global(self, global_character_id: int) -> tuple[GlobalCharacter, int]:
        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == global_character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")
        if not character.review or character.review.review_status != "completed":
            raise ValueError("완료된 리뷰가 아닙니다")
        if not character.review.cover_image_id and character.review.rating not in (-1, 0):
            raise ValueError("선택된 커버 이미지가 없습니다")

        removed = purge_noncover_images_global(self.db, character)
        commit_db_session(self.db)
        self.db.refresh(character)
        return character, removed

    def purge_unselected_images_bulk_global(self, *, search: str | None = None) -> tuple[int, int]:
        """완료된 리뷰 전체(현재 페이지 제한 없이)에서 미선택 이미지를 일괄 삭제한다."""
        query = (
            self.db.query(GlobalCharacter)
            .join(GlobalCharacter.review)
            .filter(GlobalCharacterReview.review_status == "completed")
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    GlobalCharacter.character_tag.ilike(pattern),
                    GlobalCharacter.display_name.ilike(pattern),
                )
            )
        character_ids = [row[0] for row in query.with_entities(GlobalCharacter.id).all()]

        affected = 0
        removed_total = 0
        for character_id in character_ids:
            try:
                _, removed = self.purge_unselected_images_global(character_id)
            except ValueError:
                continue
            if removed:
                affected += 1
                removed_total += removed
        return affected, removed_total
