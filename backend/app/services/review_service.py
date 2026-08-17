from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.schemas.review import V2BulkCompleteItemRequest
from app.services.character_image_service import (
    move_image_to_catalog_folder,
    purge_character_images,
    purge_global_character_images,
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

    @staticmethod
    def merge_status_fields(character: GlobalCharacter) -> dict:
        """병합(부모/자식) 상태 필드. `character.parent`/`character.children`이
        쿼리 단계에서 이미 eager load(joinedload/selectinload)되어 있어야
        N+1 없이 호출할 수 있다."""
        parent = character.parent
        return {
            "is_alternative": character.parent_character_id is not None,
            "parent_character_id": character.parent_character_id,
            "parent_character_tag": parent.character_tag if parent else None,
            "parent_display_name": parent.display_name if parent else None,
            "child_count": len(character.children),
        }

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

    def reconcile_empty_completed_reviews(self) -> int:
        """완료 처리되었지만 이미지가 하나도 남지 않은 리뷰를 다시 pending으로 되돌린다.
        rating이 0 또는 -1인 항목은 이미지가 없는 것이 정상이므로 대상에서 제외한다."""
        reviews = (
            self.db.query(Review)
            .join(Character, Character.id == Review.character_id)
            .filter(
                Review.review_status == "completed",
                # rating이 NULL인 경우 `NOT IN`은 NULL로 평가돼 대상에서 빠지므로 명시적으로 포함한다.
                or_(Review.rating.is_(None), Review.rating.notin_((0, -1))),
                ~exists().where(Image.character_id == Character.id, Image.is_rejected.is_(False)),
            )
            .all()
        )
        reverted = 0
        for review in reviews:
            if review.rating in (0, -1):
                continue
            review.review_status = "pending"
            review.cover_image_id = None
            reverted += 1
        if reverted:
            commit_db_session(self.db)
        return reverted

    def reconcile_empty_completed_reviews_global(self) -> int:
        reviews = (
            self.db.query(GlobalCharacterReview)
            .join(GlobalCharacter, GlobalCharacter.id == GlobalCharacterReview.global_character_id)
            .filter(
                GlobalCharacterReview.review_status == "completed",
                # rating이 NULL인 경우 `NOT IN`은 NULL로 평가돼 대상에서 빠지므로 명시적으로 포함한다.
                or_(
                    GlobalCharacterReview.rating.is_(None),
                    GlobalCharacterReview.rating.notin_((0, -1)),
                ),
                ~exists().where(
                    GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                    GlobalCharacterImage.is_rejected.is_(False),
                ),
            )
            .all()
        )
        reverted = 0
        for review in reviews:
            if review.rating in (0, -1):
                continue
            review.review_status = "pending"
            review.cover_image_id = None
            reverted += 1
        if reverted:
            commit_db_session(self.db)
        return reverted

    def list_catalog_reviews(
        self,
        *,
        series_id: int,
        filter_status: str = "pending",
        search: str | None = None,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[Series, list[Character], int]:
        self.reconcile_empty_completed_reviews()
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
        elif filter_status in ("completed", "completed_recent"):
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
        if filter_status == "completed_recent":
            # 최근에 결정한 항목부터 보여줘 잘못 매긴 레이팅을 바로 찾아 되돌릴 수 있게 한다.
            ordering = (Review.updated_at.desc(), Character.id.desc())
        else:
            ordering = (Character.post_count.desc(), Character.character_tag.asc(), Character.id.asc())
        items = query.order_by(*ordering).offset(skip).limit(limit).all()
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
        self.reconcile_empty_completed_reviews_global()
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
        elif filter_status in ("completed", "completed_recent"):
            query = query.filter(GlobalCharacterReview.review_status == "completed")

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(GlobalCharacter.character_tag.ilike(pattern), GlobalCharacter.display_name.ilike(pattern))
            )

        total = query.order_by(None).count()
        if filter_status == "completed_recent":
            # 최근에 결정한 항목부터 보여줘 잘못 매긴 레이팅을 바로 찾아 되돌릴 수 있게 한다.
            ordering = (GlobalCharacterReview.updated_at.desc(), GlobalCharacter.id.desc())
        else:
            ordering = (
                GlobalCharacter.post_count.desc(),
                GlobalCharacter.character_tag.asc(),
                GlobalCharacter.id.asc(),
            )
        items = query.order_by(*ordering).offset(skip).limit(limit).all()
        return items, total

    # Provenance filter (§6). Matches the compact review_note marker written by the
    # pending inspection service: `auto_inspection_result=v1;outcome=<x>;reason=...`.
    _INSPECTION_OUTCOME_GROUPS: dict[str, tuple[str, ...]] = {
        "needs_user": ("suspect", "auto_zero", "auto_minus_one", "tagger_error", "undecided"),
        "suspect": ("suspect",),
        "auto_zero": ("auto_zero",),
        "auto_minus_one": ("auto_minus_one",),
        "regenerated_pass": ("regenerated_pass",),
        "auto_pass": ("pass", "prefill_three", "auto_one"),
        "uninspected": (),  # special-cased below
    }

    def _inspection_outcome_filter(self, value: str):
        if value not in self._INSPECTION_OUTCOME_GROUPS:
            raise ValueError(
                "inspection_outcome must be one of "
                + ", ".join(sorted(self._INSPECTION_OUTCOME_GROUPS))
            )
        note = GlobalCharacterReview.review_note
        if value == "uninspected":
            # No provenance marker at all, or the tagger failed to inspect it.
            return or_(
                GlobalCharacterReview.id.is_(None),
                note.is_(None),
                not_(note.like("%auto_inspection_result=%")),
                note.like("%outcome=tagger_error;%"),
            )
        outcomes = self._INSPECTION_OUTCOME_GROUPS[value]
        return or_(*(note.like(f"%outcome={outcome};%") for outcome in outcomes))

    def list_v2_review_characters(
        self,
        *,
        review_status: str | None = None,
        rating: str | None = None,
        quality_status: str | None = None,
        identity_status: str | None = None,
        generation_status: str | None = None,
        gender: str | None = None,
        non_human: str | None = None,
        series_id: int | None = None,
        multicolor: str | None = None,
        prompt_modified: bool | None = None,
        inspection_outcome: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[list[GlobalCharacter], int]:
        if non_human not in (None, "all", "human", "non_human"):
            raise ValueError("non_human must be one of all, human, non_human")

        query = (
            self.db.query(GlobalCharacter)
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .options(
                joinedload(GlobalCharacter.images),
                joinedload(GlobalCharacter.review),
                joinedload(GlobalCharacter.parent),
                selectinload(GlobalCharacter.children),
                selectinload(GlobalCharacter.series_links).joinedload(CharacterSeriesLink.series),
            )
        )

        if review_status:
            if review_status == "pending":
                query = query.filter(
                    or_(
                        GlobalCharacterReview.id.is_(None),
                        GlobalCharacterReview.review_status == "pending",
                    )
                )
            elif review_status == "completed_recent":
                query = query.filter(GlobalCharacterReview.review_status == "completed")
            else:
                query = query.filter(GlobalCharacterReview.review_status == review_status)

        if rating:
            if rating == "unrated":
                query = query.filter(
                    or_(GlobalCharacterReview.id.is_(None), GlobalCharacterReview.rating.is_(None))
                )
            else:
                try:
                    rating_value = int(rating)
                except ValueError as exc:
                    raise ValueError("rating must be an integer or 'unrated'") from exc
                if rating_value not in (-1, 0, 1, 2, 3, 4, 5, 6):
                    raise ValueError("rating must be between -1 and 6")
                query = query.filter(GlobalCharacterReview.rating == rating_value)

        if quality_status:
            query = query.filter(
                exists(
                    select(1).where(
                        GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                        GlobalCharacterImage.quality_status == quality_status,
                        GlobalCharacterImage.is_rejected.is_(False),
                    )
                )
            )
        if identity_status:
            query = query.filter(
                exists(
                    select(1).where(
                        GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                        GlobalCharacterImage.identity_status == identity_status,
                        GlobalCharacterImage.is_rejected.is_(False),
                    )
                )
            )
        if generation_status:
            query = query.filter(GlobalCharacter.generation_status == generation_status)
        if gender:
            normalized_gender = normalize_gender(gender) or gender
            query = query.filter(
                or_(
                    GlobalCharacterReview.gender == normalized_gender,
                    GlobalCharacter.gender == normalized_gender,
                )
            )
        is_non_human = and_(
            GlobalCharacter.non_human_review_status != "excluded",
            or_(
                GlobalCharacter.non_human_candidate_score >= 0.5,
                GlobalCharacter.non_human_review_status == "confirmed",
            ),
        )
        if non_human == "non_human":
            query = query.filter(is_non_human)
        elif non_human == "human":
            query = query.filter(not_(is_non_human))
        if series_id is not None:
            query = query.join(
                CharacterSeriesLink,
                CharacterSeriesLink.global_character_id == GlobalCharacter.id,
            ).filter(CharacterSeriesLink.series_id == series_id)
        if multicolor == "has":
            query = query.filter(GlobalCharacter.multi_color_hair.is_not(None), GlobalCharacter.multi_color_hair != "")
        elif multicolor == "suggested":
            query = query.filter(
                exists(
                    select(1).where(
                        GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                        GlobalCharacterImage.suggested_multicolor_tags.is_not(None),
                        GlobalCharacterImage.suggested_multicolor_tags != "",
                        GlobalCharacterImage.is_rejected.is_(False),
                    )
                )
            )
        if prompt_modified is True:
            query = query.filter(
                GlobalCharacter.previous_base_prompt.is_not(None),
                GlobalCharacter.base_prompt != GlobalCharacter.previous_base_prompt,
            )
        elif prompt_modified is False:
            query = query.filter(
                or_(
                    GlobalCharacter.previous_base_prompt.is_(None),
                    GlobalCharacter.base_prompt == GlobalCharacter.previous_base_prompt,
                )
            )
        if inspection_outcome:
            query = query.filter(self._inspection_outcome_filter(inspection_outcome))

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    GlobalCharacter.character_tag.ilike(pattern),
                    GlobalCharacter.display_name.ilike(pattern),
                )
            )

        query = query.distinct()
        total = query.order_by(None).count()
        if review_status == "completed_recent":
            ordering = (GlobalCharacterReview.updated_at.desc(), GlobalCharacter.id.desc())
        else:
            ordering = (GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc())
        items = (
            query.order_by(*ordering)
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def save_v2_review_character(
        self,
        character_id: int,
        *,
        review_status: str,
        cover_image_id: int | None = None,
        gender: str | None = None,
        rating: int | None = None,
        base_prompt: str | None = None,
        selected_tags: str | None = None,
    ) -> GlobalCharacter:
        if review_status not in ("in_progress", "completed"):
            raise ValueError("Invalid review status")
        if rating is not None and rating not in (-1, 0, 1, 2, 3, 4, 5, 6):
            raise ValueError("rating must be between -1 and 6")

        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == character_id)
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
        if normalized_gender:
            character.gender = normalized_gender
            review.gender = normalized_gender

        if base_prompt is not None:
            next_prompt = base_prompt.strip() or None
            if character.base_prompt != next_prompt:
                character.previous_base_prompt = character.base_prompt
                character.base_prompt = next_prompt

        if cover_image_id is not None:
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
        review.selected_tags = selected_tags
        review.final_prompt = character.base_prompt
        review.review_status = review_status
        review.rating_stage = "primary"

        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def bulk_complete_v2_review_characters(
        self, items: list[V2BulkCompleteItemRequest]
    ) -> tuple[int, int, int, list[dict]]:
        completed = 0
        skipped = 0
        failed = 0
        results: list[dict] = []

        for item in items:
            if item.rating is None:
                skipped += 1
                results.append({"character_id": item.character_id, "status": "skipped"})
                continue

            try:
                cover_image_id = item.cover_image_id
                if cover_image_id is None:
                    character = (
                        self.db.query(GlobalCharacter)
                        .options(joinedload(GlobalCharacter.images))
                        .filter(GlobalCharacter.id == item.character_id)
                        .first()
                    )
                    if not character:
                        raise ValueError("Character not found")
                    visible_images = sorted(
                        (image for image in character.images if not image.is_rejected),
                        key=lambda image: (not image.is_cover, -(image.cover_score or 0), image.id),
                    )
                    if visible_images:
                        cover_image_id = visible_images[0].id

                self.save_v2_review_character(
                    item.character_id,
                    review_status="completed",
                    cover_image_id=cover_image_id,
                    gender=item.gender,
                    rating=item.rating,
                    base_prompt=item.base_prompt,
                    selected_tags=item.selected_tags,
                )
                completed += 1
                results.append({"character_id": item.character_id, "status": "completed"})
            except ValueError as exc:
                self.db.rollback()
                failed += 1
                results.append({"character_id": item.character_id, "status": "failed", "error": str(exc)})

        return completed, skipped, failed, results

    def get_v2_review_stats(self) -> dict[str, int]:
        rows = (
            self.db.query(
                func.coalesce(GlobalCharacterReview.review_status, "pending").label("status"),
                func.count(GlobalCharacter.id),
            )
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .group_by("status")
            .all()
        )
        stats = {"total": 0, "pending": 0, "in_progress": 0, "completed": 0}
        for status, count in rows:
            stats["total"] += count
            if status in stats:
                stats[status] = count
        return stats

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

    @staticmethod
    def _preview_image(image: Image | GlobalCharacterImage) -> dict[str, object]:
        return {"id": image.id, "image_path": image.image_path}

    @staticmethod
    def _selected_and_delete_images(
        images: list[Image] | list[GlobalCharacterImage],
        cover_image_id: int | None,
    ) -> tuple[Image | GlobalCharacterImage | None, list[Image | GlobalCharacterImage]]:
        selected = next((image for image in images if image.id == cover_image_id), None) if cover_image_id else None
        delete_images = [image for image in images if image.id != cover_image_id]
        return selected, delete_images

    def _purge_images_except_cover_id(
        self,
        character: Character | GlobalCharacter,
        image_model: type[Image] | type[GlobalCharacterImage],
        owner_column,
        owner_id: int,
        cover_image_id: int | None,
    ) -> int:
        query = self.db.query(image_model).filter(owner_column == owner_id)
        if cover_image_id is not None:
            query = query.filter(image_model.id != cover_image_id)
        images = query.all()
        removed = 0
        for image in images:
            file_path = settings.project_root / image.image_path
            if file_path.is_file():
                file_path.unlink()
            self.db.delete(image)
            if image in character.images:
                character.images.remove(image)
            removed += 1
        if removed:
            self.db.flush()
        return removed

    def _catalog_purge_preview_item(self, character: Character) -> dict[str, object] | None:
        review = character.review
        if not review or review.review_status != "completed" or review.rating is None:
            return None
        selected, delete_images = self._selected_and_delete_images(list(character.images), review.cover_image_id)
        if review.rating not in (-1, 0) and selected is None:
            return None
        if not delete_images:
            return None
        return {
            "character_id": character.id,
            "character_tag": character.character_tag,
            "display_name": character.display_name or character.character_tag,
            "rating": review.rating,
            "selected_image": self._preview_image(selected) if selected else None,
            "delete_images": [self._preview_image(image) for image in delete_images],
        }

    def _catalog_global_purge_preview_item(self, character: GlobalCharacter) -> dict[str, object] | None:
        review = character.review
        if not review or review.review_status != "completed" or review.rating is None:
            return None
        selected, delete_images = self._selected_and_delete_images(list(character.images), review.cover_image_id)
        if review.rating not in (-1, 0) and selected is None:
            return None
        if not delete_images:
            return None
        return {
            "character_id": character.id,
            "character_tag": character.character_tag,
            "display_name": character.display_name or character.character_tag,
            "rating": review.rating,
            "selected_image": self._preview_image(selected) if selected else None,
            "delete_images": [self._preview_image(image) for image in delete_images],
        }

    def _catalog_purge_query(self, series_id: int, *, search: str | None = None):
        query = (
            self.db.query(Character)
            .join(Character.review)
            .options(joinedload(Character.images), joinedload(Character.review))
            .filter(
                Character.series_id == series_id,
                Review.review_status == "completed",
                Review.rating.isnot(None),
            )
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(or_(Character.character_tag.ilike(pattern), Character.display_name.ilike(pattern)))
        return query

    def _catalog_global_purge_query(self, *, search: str | None = None):
        query = (
            self.db.query(GlobalCharacter)
            .join(GlobalCharacter.review)
            .options(joinedload(GlobalCharacter.images), joinedload(GlobalCharacter.review))
            .filter(
                GlobalCharacterReview.review_status == "completed",
                GlobalCharacterReview.rating.isnot(None),
            )
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(GlobalCharacter.character_tag.ilike(pattern), GlobalCharacter.display_name.ilike(pattern))
            )
        return query

    @staticmethod
    def _preview_response(items: list[dict[str, object]]) -> dict[str, object]:
        return {
            "items": items,
            "item_count": len(items),
            "image_count": sum(len(item["delete_images"]) for item in items),
        }

    def preview_purge_unselected_images(self, series_id: int, *, search: str | None = None) -> dict[str, object]:
        if not self.db.query(Series.id).filter(Series.id == series_id).first():
            raise ValueError("Series not found")
        items = [
            item
            for character in self._catalog_purge_query(series_id, search=search)
            .order_by(Character.post_count.desc(), Character.character_tag.asc(), Character.id.asc())
            .all()
            if (item := self._catalog_purge_preview_item(character)) is not None
        ]
        return self._preview_response(items)

    def preview_purge_unselected_images_global(self, *, search: str | None = None) -> dict[str, object]:
        items = [
            item
            for character in self._catalog_global_purge_query(search=search)
            .order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc())
            .all()
            if (item := self._catalog_global_purge_preview_item(character)) is not None
        ]
        return self._preview_response(items)

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

        removed = self._purge_images_except_cover_id(
            character,
            Image,
            Image.character_id,
            character.id,
            character.review.cover_image_id,
        )
        commit_db_session(self.db)
        self.db.refresh(character)
        return character, removed

    def purge_unselected_images_bulk(self, series_id: int, *, search: str | None = None) -> tuple[int, int]:
        """완료된 리뷰 전체(현재 페이지 제한 없이)에서 미선택 이미지를 일괄 삭제한다."""
        character_ids = [
            row[0] for row in self._catalog_purge_query(series_id, search=search).with_entities(Character.id).all()
        ]
        if not character_ids:
            return 0, 0

        return self.purge_unselected_images_selected(series_id, character_ids)

    def purge_unselected_images_selected(self, series_id: int, character_ids: list[int]) -> tuple[int, int]:
        if not character_ids:
            raise ValueError("character_ids must not be empty")
        if not self.db.query(Series.id).filter(Series.id == series_id).first():
            raise ValueError("Series not found")

        scope_ids = {
            row[0]
            for row in self.db.query(Character.id)
            .filter(Character.id.in_(character_ids), Character.series_id == series_id)
            .all()
        }
        outside_scope = [character_id for character_id in character_ids if character_id not in scope_ids]
        if outside_scope:
            raise ValueError(f"Character {outside_scope[0]} is outside the requested series scope")

        characters = (
            self._catalog_purge_query(series_id)
            .filter(Character.id.in_(character_ids))
            .order_by(Character.id.asc())
            .all()
        )

        affected = 0
        removed_total = 0
        for character in characters:
            if self._catalog_purge_preview_item(character) is None:
                continue
            removed = self._purge_images_except_cover_id(
                character,
                Image,
                Image.character_id,
                character.id,
                character.review.cover_image_id,
            )
            if removed:
                affected += 1
                removed_total += removed
        if removed_total:
            commit_db_session(self.db)
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

        removed = self._purge_images_except_cover_id(
            character,
            GlobalCharacterImage,
            GlobalCharacterImage.global_character_id,
            character.id,
            character.review.cover_image_id,
        )
        commit_db_session(self.db)
        self.db.refresh(character)
        return character, removed

    def purge_unselected_images_bulk_global(self, *, search: str | None = None) -> tuple[int, int]:
        """완료된 리뷰 전체(현재 페이지 제한 없이)에서 미선택 이미지를 일괄 삭제한다."""
        character_ids = [
            row[0] for row in self._catalog_global_purge_query(search=search).with_entities(GlobalCharacter.id).all()
        ]
        if not character_ids:
            return 0, 0

        return self.purge_unselected_images_selected_global(character_ids)

    def purge_unselected_images_selected_global(self, character_ids: list[int]) -> tuple[int, int]:
        if not character_ids:
            raise ValueError("character_ids must not be empty")
        existing_ids = {
            row[0]
            for row in self.db.query(GlobalCharacter.id).filter(GlobalCharacter.id.in_(character_ids)).all()
        }
        missing_ids = [character_id for character_id in character_ids if character_id not in existing_ids]
        if missing_ids:
            raise ValueError(f"Character not found: {missing_ids[0]}")

        characters = (
            self._catalog_global_purge_query()
            .filter(GlobalCharacter.id.in_(character_ids))
            .order_by(GlobalCharacter.id.asc())
            .all()
        )
        affected = 0
        removed_total = 0
        for character in characters:
            if self._catalog_global_purge_preview_item(character) is None:
                continue
            removed = self._purge_images_except_cover_id(
                character,
                GlobalCharacterImage,
                GlobalCharacterImage.global_character_id,
                character.id,
                character.review.cover_image_id,
            )
            if removed:
                affected += 1
                removed_total += removed
        if removed_total:
            commit_db_session(self.db)
        return affected, removed_total
