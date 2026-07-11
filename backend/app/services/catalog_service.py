from datetime import datetime
import csv
import io
from pathlib import Path

from sqlalchemy import Float, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, contains_eager, selectinload

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
from app.schemas.character import CATALOG_EXPORT_COLUMNS
from app.services.character_image_service import purge_character_images, purge_global_character_images
from app.services.db_write_queue import commit_db_session
from app.services.prompt_service import (
    build_generation_prompt,
    mask_appearance_for_catalog,
    mask_appearance_for_global_catalog,
)


def catalog_status_expression():
    has_cover = exists(
        select(1).where(
            Image.character_id == Character.id,
            Image.is_cover.is_(True),
        )
    )
    return case(
        (Character.status == "excluded", "excluded"),
        (Character.status == "tag_needs_check", "tag_needs_check"),
        (
            and_(
                Review.review_status == "completed",
                or_(has_cover, Review.rating.in_((0, -1))),
            ),
            "completed",
        ),
        (Review.review_status == "needs_regen", "needs_regen"),
        (Review.review_status == "pending", "needs_review"),
        (~has_cover, "missing_image"),
        (Character.status.in_(["needs_check", "confirmed"]), "needs_review"),
        else_="needs_review",
    )


# Default rating weights for random pick (tunable later via settings).
RATING_WEIGHTS: dict[int | None, float] = {
    None: 0.5,
    -1: 0.25,
    0: 0.5,
    1: 1.0,
    2: 1.5,
    3: 2.0,
    4: 3.0,
    5: 4.0,
    6: 5.0,
}


def rating_weight_expression():
    branches: list[tuple] = [(Review.rating.is_(None), RATING_WEIGHTS[None])]
    branches.extend(
        (Review.rating == rating, weight)
        for rating, weight in RATING_WEIGHTS.items()
        if rating is not None
    )
    return case(*branches, else_=RATING_WEIGHTS[None]).cast(Float)


class CatalogService:
    def __init__(self, db: Session):
        self.db = db

    def _base_query(self, status_case):
        cover_exists = exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.is_cover.is_(True),
            )
        )
        return (
            self.db.query(Character)
            .join(Character.series)
            .outerjoin(Character.review)
            .options(contains_eager(Character.series), contains_eager(Character.review))
            .add_columns(status_case.label("catalog_status"), cover_exists.label("has_cover"))
        )

    def _apply_catalog_filters(
        self,
        query,
        status_case,
        *,
        series_tag: str | None = None,
        rating: int | None = None,
        gender: str | None = None,
        type_: str | None = None,
        hair_color: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
        status: str | None = None,
        has_cover_image: bool | None = None,
        needs_review: bool | None = None,
        needs_regen: bool | None = None,
        search: str | None = None,
        include_hidden_ratings: bool = False,
    ):
        if series_tag:
            query = query.filter(Series.series_tag == series_tag)
        if rating is not None:
            query = query.filter(Review.rating == rating)
        elif not include_hidden_ratings:
            # 레이팅 필터를 명시적으로 -1/0으로 선택하지 않는 한, 이미지가 없는
            # 레이팅(-1) 또는 생성 실패(0) 항목은 기본적으로 목록에서 제외한다.
            query = query.filter(or_(Review.rating.is_(None), ~Review.rating.in_((-1, 0))))
        if gender:
            query = query.filter(
                Character.appearance_confirmed.is_(True),
                Character.gender.ilike(f"%{gender}%"),
            )
        if type_:
            query = query.filter(Review.type == type_)
        if hair_color:
            query = query.filter(
                Character.appearance_confirmed.is_(True),
                Character.hair_color.ilike(f"%{hair_color}%"),
            )
        if eye_color:
            query = query.filter(
                Character.appearance_confirmed.is_(True),
                Character.eye_color.ilike(f"%{eye_color}%"),
            )
        if feature_tags:
            query = query.filter(
                Character.appearance_confirmed.is_(True),
                Character.feature_tags.ilike(f"%{feature_tags}%"),
            )
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
        if status:
            query = query.filter(status_case == status)
        if has_cover_image is True:
            query = query.filter(
                exists(
                    select(1).where(
                        Image.character_id == Character.id,
                        Image.is_cover.is_(True),
                    )
                )
            )
        elif has_cover_image is False:
            query = query.filter(
                ~exists(
                    select(1).where(
                        Image.character_id == Character.id,
                        Image.is_cover.is_(True),
                    )
                )
            )
        if needs_review is True:
            query = query.filter(status_case == "needs_review")
        if needs_regen is True:
            query = query.filter(status_case == "needs_regen")
        return query

    @staticmethod
    def _resolve_catalog_gender(character: Character) -> str | None:
        review = character.review
        raw = None
        if review and review.gender:
            raw = review.gender
        elif character.gender:
            raw = character.gender
        return normalize_gender(raw) if raw else None

    @staticmethod
    def _filter_appearance_by_selected_tags(appearance: dict[str, str | None], selected_tags: str | None) -> dict[str, str | None]:
        if not selected_tags:
            return appearance
        selected = {tag.strip() for tag in selected_tags.split(",") if tag.strip()}
        if not selected:
            return appearance
        filtered = dict(appearance)
        for field in ("multi_color_hair", "hair_color", "hair_shape", "eye_color", "feature_tags"):
            value = appearance.get(field)
            if not value:
                continue
            kept = [tag.strip() for tag in value.split(",") if tag.strip() in selected]
            filtered[field] = ", ".join(kept) or None
        return filtered

    @staticmethod
    def _build_catalog_item(character: Character, catalog_status: str, has_cover: bool, cover_image: Image | None) -> dict:
        review = character.review
        rating = review.rating if review else None
        if rating in (0, -1):
            cover_image = None
            has_cover = False

        appearance = mask_appearance_for_catalog(character)
        if cover_image is not None and review:
            # 표지 이미지가 선택된 경우, 검수 화면에서 사용자가 켠 태그만 카탈로그에 노출한다.
            appearance = CatalogService._filter_appearance_by_selected_tags(appearance, review.selected_tags)
        return {
            "id": character.id,
            "series_id": character.series_id,
            "series_tag": character.series.series_tag,
            "series_display_name": character.series.display_name,
            "character_tag": character.character_tag,
            "display_name": character.display_name or character.character_tag,
            "post_count": character.post_count,
            "danbooru_url": character.danbooru_url,
            "cover_image": cover_image.image_path if cover_image else None,
            "type": review.type if review else None,
            "rating": review.rating if review else None,
            **appearance,
            "gender": CatalogService._resolve_catalog_gender(character),
            "final_prompt": review.final_prompt if review else None,
            "character_status": character.status,
            "catalog_status": catalog_status,
            "has_cover_image": bool(has_cover),
            "needs_review": catalog_status == "needs_review",
            "needs_regen": catalog_status == "needs_regen",
        }

    def _cover_map(self, character_ids: list[int]) -> dict[int, Image]:
        if not character_ids:
            return {}
        cover_rows = (
            self.db.query(Image)
            .filter(Image.character_id.in_(character_ids), Image.is_cover.is_(True))
            .all()
        )
        return {row.character_id: row for row in cover_rows}

    def list_catalog(
        self,
        *,
        series_tag: str | None = None,
        rating: int | None = None,
        gender: str | None = None,
        type_: str | None = None,
        hair_color: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
        status: str | None = None,
        has_cover_image: bool | None = None,
        needs_review: bool | None = None,
        needs_regen: bool | None = None,
        search: str | None = None,
        include_hidden_ratings: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict], int]:
        status_case = catalog_status_expression()
        query = self._base_query(status_case)
        query = self._apply_catalog_filters(
            query,
            status_case,
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type_=type_,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
            include_hidden_ratings=include_hidden_ratings,
        )

        total = query.order_by(None).with_entities(func.count(Character.id)).scalar() or 0

        rows = (
            query.order_by(Series.post_count.desc(), Character.post_count.desc(), Character.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        page_character_ids = [character.id for character, _, _ in rows]
        purged_any = False
        for character, _, _ in rows:
            review = character.review
            if review and review.rating == 0 and character.images:
                purge_character_images(self.db, character)
                purged_any = True
        if purged_any:
            commit_db_session(self.db)
            rows = (
                query.order_by(Series.post_count.desc(), Character.post_count.desc(), Character.id.asc())
                .offset(skip)
                .limit(limit)
                .all()
            )
            page_character_ids = [character.id for character, _, _ in rows]

        cover_image_by_character = self._cover_map(page_character_ids)

        items = [
            self._build_catalog_item(
                character,
                catalog_status,
                has_cover,
                cover_image_by_character.get(character.id),
            )
            for character, catalog_status, has_cover in rows
        ]

        return items, total

    # ── 캐릭터 목록(GlobalCharacter) 리뷰 결과 병행 표시 ──────────────────────
    # 시리즈 기반 카탈로그와 완전히 독립된 데이터 소스라, 카탈로그 탭에서 함께 보여주기
    # 위해 별도 목록/아이템 빌더를 둔다. 시리즈에 아직 연결되지 않았을 수 있으므로
    # series_id/series_tag는 CharacterSeriesLink의 대표(primary) 시리즈로 채운다.

    def _global_cover_map(self, character_ids: list[int]) -> dict[int, GlobalCharacterImage]:
        if not character_ids:
            return {}
        rows = (
            self.db.query(GlobalCharacterImage)
            .filter(
                GlobalCharacterImage.global_character_id.in_(character_ids),
                GlobalCharacterImage.is_cover.is_(True),
            )
            .all()
        )
        return {row.global_character_id: row for row in rows}

    @staticmethod
    def _build_global_catalog_item(
        character: GlobalCharacter, cover_image: GlobalCharacterImage | None
    ) -> dict:
        review = character.review
        rating = review.rating if review else None
        has_cover = cover_image is not None
        if rating in (0, -1):
            cover_image = None
            has_cover = False

        appearance = mask_appearance_for_global_catalog(character)
        if cover_image is not None and review:
            appearance = CatalogService._filter_appearance_by_selected_tags(appearance, review.selected_tags)

        primary_link = next(
            (link for link in character.series_links if link.is_primary and link.series),
            next((link for link in character.series_links if link.series), None),
        )

        if review and review.review_status == "completed" and (has_cover or rating in (0, -1)):
            catalog_status = "completed"
        elif not character.images:
            catalog_status = "missing_image"
        else:
            catalog_status = "needs_review"

        gender_source = (review.gender if review and review.gender else character.gender)
        parent = character.parent

        return {
            "id": character.id,
            "is_alternative": character.parent_character_id is not None,
            "parent_character_tag": parent.character_tag if parent else None,
            "parent_display_name": parent.display_name if parent else None,
            "series_id": primary_link.series_id if primary_link else None,
            "series_tag": primary_link.series.series_tag if primary_link and primary_link.series else "",
            "series_display_name": (
                primary_link.series.display_name if primary_link and primary_link.series else ""
            ),
            "character_tag": character.character_tag,
            "display_name": character.display_name or character.character_tag,
            "post_count": character.post_count,
            "danbooru_url": None,
            "cover_image": cover_image.image_path if cover_image else None,
            "type": review.type if review else None,
            "rating": review.rating if review else None,
            **appearance,
            "gender": normalize_gender(gender_source) if gender_source else None,
            "final_prompt": review.final_prompt if review else None,
            "character_status": character.collect_status,
            "catalog_status": catalog_status,
            "has_cover_image": bool(has_cover),
            "needs_review": catalog_status == "needs_review",
            "needs_regen": False,
        }

    def list_global_catalog(
        self,
        *,
        rating: int | None = None,
        gender: str | None = None,
        search: str | None = None,
        include_hidden_ratings: bool = False,
        has_alternative: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict], int]:
        has_image = exists(
            select(1).where(GlobalCharacterImage.global_character_id == GlobalCharacter.id)
        )
        query = (
            self.db.query(GlobalCharacter)
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .options(
                selectinload(GlobalCharacter.review),
                selectinload(GlobalCharacter.images),
                selectinload(GlobalCharacter.series_links).selectinload(CharacterSeriesLink.series),
                selectinload(GlobalCharacter.parent),
            )
            .filter(has_image)
        )
        if rating is not None:
            query = query.filter(GlobalCharacterReview.rating == rating)
        elif not include_hidden_ratings:
            query = query.filter(
                or_(GlobalCharacterReview.rating.is_(None), ~GlobalCharacterReview.rating.in_((-1, 0)))
            )
        if has_alternative is True:
            query = query.filter(GlobalCharacter.parent_character_id.isnot(None))
        elif has_alternative is False:
            query = query.filter(GlobalCharacter.parent_character_id.is_(None))
        if gender:
            query = query.filter(GlobalCharacter.gender.ilike(f"%{gender}%"))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    GlobalCharacter.character_tag.ilike(pattern),
                    GlobalCharacter.display_name.ilike(pattern),
                )
            )

        total = query.order_by(None).with_entities(func.count(GlobalCharacter.id)).scalar() or 0

        rows = (
            query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        character_ids = [character.id for character in rows]
        purged_any = False
        for character in rows:
            review = character.review
            if review and review.rating == 0 and character.images:
                purge_global_character_images(self.db, character)
                purged_any = True
        if purged_any:
            commit_db_session(self.db)
            rows = (
                query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.id.asc())
                .offset(skip)
                .limit(limit)
                .all()
            )
            character_ids = [character.id for character in rows]

        cover_map = self._global_cover_map(character_ids)
        items = [
            self._build_global_catalog_item(character, cover_map.get(character.id)) for character in rows
        ]
        return items, total

    def get_stats(self) -> dict[str, int]:
        series_count = self.db.query(Series).count()
        character_count = self.db.query(Character).count()
        review_count = self.db.query(Review).filter(Review.review_status == "completed").count()
        cover_count = (
            self.db.query(Image)
            .join(Review, Review.character_id == Image.character_id)
            .filter(Image.is_cover.is_(True), or_(Review.rating.is_(None), ~Review.rating.in_((0, -1))))
            .count()
        )
        return {
            "series_count": series_count,
            "character_count": character_count,
            "completed_count": review_count,
            "cover_image_count": cover_count,
        }

    def get_random_character(
        self,
        *,
        series_tag: str | None = None,
        rating: int | None = None,
        gender: str | None = None,
        type_: str | None = None,
        hair_color: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
        status: str | None = None,
        has_cover_image: bool | None = True,
        needs_review: bool | None = None,
        needs_regen: bool | None = None,
        search: str | None = None,
        include_hidden_ratings: bool = False,
    ) -> dict | None:
        status_case = catalog_status_expression()
        query = self._base_query(status_case)
        query = self._apply_catalog_filters(
            query,
            status_case,
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type_=type_,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
            include_hidden_ratings=include_hidden_ratings,
        )

        weight = rating_weight_expression()
        weighted_score = (-func.ln(func.random()) / weight).label("pick_score")
        row = query.add_columns(weighted_score).order_by(weighted_score.desc()).limit(1).first()
        if not row:
            return None

        character, catalog_status, has_cover, _pick_score = row
        cover_image = self._cover_map([character.id]).get(character.id)
        return self._build_catalog_item(character, catalog_status, has_cover, cover_image)

    def update_catalog_item(
        self,
        character_id: int,
        *,
        multi_color_hair: str | None = None,
        hair_color: str | None = None,
        hair_shape: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
        gender: str | None = None,
        rating: int | None = None,
        type_: str | None = None,
        final_prompt: str | None = None,
    ) -> dict:
        status_case = catalog_status_expression()
        cover_exists = exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.is_cover.is_(True),
            )
        )
        row = (
            self.db.query(Character)
            .join(Character.series)
            .outerjoin(Character.review)
            .options(contains_eager(Character.series), contains_eager(Character.review))
            .add_columns(status_case.label("catalog_status"), cover_exists.label("has_cover"))
            .filter(Character.id == character_id)
            .first()
        )
        if not row:
            raise ValueError("Character not found")

        character, catalog_status, has_cover = row
        appearance_changed = False

        if multi_color_hair is not None:
            character.multi_color_hair = multi_color_hair or None
            appearance_changed = True
        if hair_color is not None:
            character.hair_color = hair_color or None
            appearance_changed = True
        if hair_shape is not None:
            character.hair_shape = hair_shape or None
            appearance_changed = True
        if eye_color is not None:
            character.eye_color = eye_color or None
            appearance_changed = True
        if feature_tags is not None:
            character.feature_tags = feature_tags or None
            appearance_changed = True
        if gender is not None:
            normalized = normalize_gender(gender) if gender else None
            character.gender = normalized
            appearance_changed = True

        if appearance_changed:
            character.generation_prompt = build_generation_prompt(character)

        review = character.review
        if rating is not None or type_ is not None or final_prompt is not None or gender is not None:
            if not review:
                review = Review(character_id=character.id)
                self.db.add(review)
                character.review = review
            if gender is not None:
                review.gender = normalize_gender(gender) if gender else None
            if rating is not None:
                review.rating = rating
                if rating == 0:
                    purge_character_images(self.db, character)
            if type_ is not None:
                review.type = type_ or None
            if final_prompt is not None:
                review.final_prompt = final_prompt or None

        commit_db_session(self.db)
        self.db.refresh(character)

        cover_image = self._cover_map([character.id]).get(character.id)
        return self._build_catalog_item(character, catalog_status, has_cover, cover_image)

    def export_catalog_csv(
        self,
        *,
        series_tag: str | None = None,
        rating: int | None = None,
        gender: str | None = None,
        type_: str | None = None,
        hair_color: str | None = None,
        eye_color: str | None = None,
        feature_tags: str | None = None,
        status: str | None = None,
        has_cover_image: bool | None = None,
        needs_review: bool | None = None,
        needs_regen: bool | None = None,
        search: str | None = None,
        include_hidden_ratings: bool = False,
        save_to_disk: bool = True,
    ) -> tuple[str, str | None]:
        status_case = catalog_status_expression()
        query = self._base_query(status_case)
        query = self._apply_catalog_filters(
            query,
            status_case,
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type_=type_,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
            include_hidden_ratings=include_hidden_ratings,
        )
        rows = query.order_by(Series.series_tag.asc(), Character.post_count.desc(), Character.id.asc()).all()
        character_ids = [character.id for character, _, _ in rows]
        cover_map = self._cover_map(character_ids)

        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow(CATALOG_EXPORT_COLUMNS)
        for character, catalog_status, has_cover in rows:
            item = self._build_catalog_item(
                character,
                catalog_status,
                has_cover,
                cover_map.get(character.id),
            )
            writer.writerow(
                [
                    item["series_tag"],
                    item["series_display_name"],
                    item["character_tag"],
                    item["display_name"],
                    item["post_count"],
                    item["catalog_status"],
                    item["character_status"],
                    item.get("gender") or "",
                    item.get("type") or "",
                    item["rating"] if item["rating"] is not None else "",
                    item.get("hair_color") or "",
                    item.get("multi_color_hair") or "",
                    item.get("hair_shape") or "",
                    item.get("eye_color") or "",
                    item.get("feature_tags") or "",
                    item.get("generation_prompt") or "",
                    item.get("final_prompt") or "",
                    item.get("cover_image") or "",
                    item.get("danbooru_url") or "",
                ]
            )

        content = output.getvalue()
        saved_path: str | None = None
        if save_to_disk:
            export_dir = settings.output_dir / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            filename = f"catalog_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
            path = export_dir / filename
            path.write_text(content, encoding="utf-8-sig")
            saved_path = str(path.relative_to(settings.project_root)).replace("\\", "/")

        return content, saved_path
