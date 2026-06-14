from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.character import Character
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series


def compute_catalog_status(character: Character, review: Review | None, cover_image: Image | None) -> str:
    if character.status == "excluded":
        return "excluded"
    if character.status == "tag_needs_check":
        return "tag_needs_check"
    if review and review.review_status == "completed" and cover_image:
        return "completed"
    if review and review.review_status == "needs_regen":
        return "needs_regen"
    if review and review.review_status == "pending":
        return "needs_review"
    if not cover_image:
        return "missing_image"
    if character.status in {"needs_check", "confirmed"}:
        return "needs_review"
    return "needs_review"


class CatalogService:
    def __init__(self, db: Session):
        self.db = db

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
        query = (
            self.db.query(Character)
            .join(Series)
            .outerjoin(Review)
            .options(joinedload(Character.series), joinedload(Character.review))
        )

        if series_tag:
            query = query.filter(Series.series_tag == series_tag)
        if rating is not None:
            query = query.filter(Review.rating == rating)
        if gender:
            query = query.filter(Review.gender == gender)
        if type_:
            query = query.filter(Review.type == type_)
        if hair_color:
            query = query.filter(Character.hair_color.ilike(f"%{hair_color}%"))
        if eye_color:
            query = query.filter(Character.eye_color.ilike(f"%{eye_color}%"))
        if feature_tags:
            query = query.filter(Character.feature_tags.ilike(f"%{feature_tags}%"))
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

        characters = query.order_by(Series.post_count.desc(), Character.post_count.desc(), Character.id.asc()).all()
        items: list[dict] = []

        for character in characters:
            cover_image = (
                self.db.query(Image)
                .filter(Image.character_id == character.id, Image.is_cover.is_(True))
                .first()
            )
            review = character.review
            catalog_status = compute_catalog_status(character, review, cover_image)

            if status and catalog_status != status:
                continue
            if has_cover_image is True and not cover_image:
                continue
            if has_cover_image is False and cover_image:
                continue
            if needs_review is True and catalog_status != "needs_review":
                continue
            if needs_regen is True and catalog_status != "needs_regen":
                continue

            items.append(
                {
                    "id": character.id,
                    "series_tag": character.series.series_tag,
                    "series_display_name": character.series.display_name,
                    "character_tag": character.character_tag,
                    "display_name": character.display_name or character.character_tag,
                    "danbooru_url": character.danbooru_url,
                    "cover_image": cover_image.image_path if cover_image else None,
                    "gender": review.gender if review else None,
                    "type": review.type if review else None,
                    "rating": review.rating if review else None,
                    "multi_color_hair": character.multi_color_hair,
                    "hair_color": character.hair_color,
                    "hair_shape": character.hair_shape,
                    "eye_color": character.eye_color,
                    "feature_tags": character.feature_tags,
                    "final_prompt": review.final_prompt if review else None,
                    "character_status": character.status,
                    "catalog_status": catalog_status,
                    "has_cover_image": cover_image is not None,
                    "needs_review": catalog_status == "needs_review",
                    "needs_regen": catalog_status == "needs_regen",
                }
            )

        total = len(items)
        return items[skip : skip + limit], total

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
