from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.models.character import Character
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.services.prompt_service import mask_appearance_for_catalog


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
        (and_(Review.review_status == "completed", has_cover), "completed"),
        (Review.review_status == "needs_regen", "needs_regen"),
        (Review.review_status == "pending", "needs_review"),
        (~has_cover, "missing_image"),
        (Character.status.in_(["needs_check", "confirmed"]), "needs_review"),
        else_="needs_review",
    )


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
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict], int]:
        status_case = catalog_status_expression()
        query = self._base_query(status_case)

        if series_tag:
            query = query.filter(Series.series_tag == series_tag)
        if rating is not None:
            query = query.filter(Review.rating == rating)
        if gender:
            query = query.filter(Review.gender == gender)
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

        total = query.order_by(None).with_entities(func.count(Character.id)).scalar() or 0

        rows = (
            query.order_by(Series.post_count.desc(), Character.post_count.desc(), Character.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        page_character_ids = [character.id for character, _, _ in rows]
        cover_image_by_character = {}
        if page_character_ids:
            cover_rows = (
                self.db.query(Image)
                .filter(Image.character_id.in_(page_character_ids), Image.is_cover.is_(True))
                .all()
            )
            cover_image_by_character = {row.character_id: row for row in cover_rows}

        items: list[dict] = []
        for character, catalog_status, has_cover in rows:
            cover_image = cover_image_by_character.get(character.id)
            review = character.review
            appearance = mask_appearance_for_catalog(character)
            items.append(
                {
                    "id": character.id,
                    "series_tag": character.series.series_tag,
                    "series_display_name": character.series.display_name,
                    "character_tag": character.character_tag,
                    "display_name": character.display_name or character.character_tag,
                    "post_count": character.post_count,
                    "danbooru_url": character.danbooru_url,
                    "cover_image": cover_image.image_path if cover_image else None,
                    "gender": review.gender if review else None,
                    "type": review.type if review else None,
                    "rating": review.rating if review else None,
                    **appearance,
                    "final_prompt": review.final_prompt if review else None,
                    "character_status": character.status,
                    "catalog_status": catalog_status,
                    "has_cover_image": bool(has_cover),
                    "needs_review": catalog_status == "needs_review",
                    "needs_regen": catalog_status == "needs_regen",
                }
            )

        return items, total

    def get_stats(self) -> dict[str, int]:
        series_count = self.db.query(Series).count()
        character_count = self.db.query(Character).count()
        review_count = self.db.query(Review).filter(Review.review_status == "completed").count()
        cover_count = self.db.query(Image).filter(Image.is_cover.is_(True)).count()
        return {
            "series_count": series_count,
            "character_count": character_count,
            "completed_count": review_count,
            "cover_image_count": cover_count,
        }
