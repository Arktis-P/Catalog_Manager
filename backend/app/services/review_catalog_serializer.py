from __future__ import annotations

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character
from app.schemas.review import CatalogReviewImageResponse, CatalogReviewItemResponse
from app.services.review_service import ReviewService


def visible_catalog_images(character: Character) -> list:
    return sorted(
        [image for image in character.images if not image.is_rejected],
        key=lambda image: image.created_at,
    )[:4]


def to_catalog_item(character: Character) -> CatalogReviewItemResponse:
    series = character.series
    review = character.review
    images = visible_catalog_images(character)
    return CatalogReviewItemResponse(
        id=character.id,
        series_tag=series.series_tag,
        series_display_name=series.display_name,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        danbooru_url=character.danbooru_url,
        danbooru_wiki_url=ReviewService.build_wiki_url(character.character_tag),
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        gender=normalize_gender(review.gender if review and review.gender else character.gender),
        generation_prompt=character.generation_prompt,
        character_status=character.status,
        needs_check_reason=character.needs_check_reason,
        review_status=review.review_status if review else None,
        rating=review.rating if review else None,
        type=review.type if review else None,
        final_prompt=review.final_prompt if review else None,
        cover_image_id=review.cover_image_id if review else None,
        images=[
            CatalogReviewImageResponse(
                id=image.id,
                image_path=image.image_path,
                auto_status=image.auto_status,
                cover_score=image.cover_score,
                hair_match=image.hair_match,
                eye_match=image.eye_match,
                gender_pred=image.gender_pred,
                is_rejected=image.is_rejected,
                is_cover=image.is_cover,
            )
            for image in images
        ],
    )
