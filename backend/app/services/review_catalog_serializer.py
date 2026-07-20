from __future__ import annotations

import json

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.schemas.review import (
    CatalogReviewImageResponse,
    CatalogReviewItemResponse,
    GlobalCatalogReviewItemResponse,
)
from app.services.review_service import ReviewService


def parse_json_reason_list(value: str | None) -> list[str]:
    """quality_reasons/identity_reasons/suggested_multicolor_tags에 저장된
    JSON 배열 문자열을 리스트로 파싱한다. 값이 없거나 형식이 어긋나면 빈 리스트."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def visible_catalog_images(character: Character) -> list:
    return sorted(
        [image for image in character.images if not image.is_rejected],
        key=lambda image: image.created_at,
    )[:4]


def visible_catalog_images_global(character: GlobalCharacter) -> list:
    return sorted(
        [image for image in character.images if not image.is_rejected],
        key=lambda image: image.created_at,
    )[:4]


def to_catalog_item_global(character: GlobalCharacter) -> GlobalCatalogReviewItemResponse:
    review = character.review
    images = visible_catalog_images_global(character)
    parent = character.parent
    return GlobalCatalogReviewItemResponse(
        id=character.id,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        danbooru_url=None,
        danbooru_wiki_url=ReviewService.build_wiki_url(character.character_tag),
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        gender=normalize_gender(review.gender if review and review.gender else character.gender),
        generation_prompt=getattr(character, "generation_prompt", None),
        character_status=character.collect_status,
        review_status=review.review_status if review else None,
        rating=review.rating if review else None,
        type=review.type if review else None,
        final_prompt=review.final_prompt if review else None,
        cover_image_id=review.cover_image_id if review else None,
        parent_character_tag=parent.character_tag if parent else None,
        parent_display_name=parent.display_name if parent else None,
        is_alternative=character.parent_character_id is not None,
        child_count=len(character.children),
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
                is_provisional=image.is_provisional,
                quality_status=image.quality_status,
                quality_score=image.quality_score,
                quality_reasons=parse_json_reason_list(image.quality_reasons),
                identity_status=image.identity_status,
                character_confidence=image.character_confidence,
                hair_color_confidence=image.hair_color_confidence,
                conflicting_character_tag=image.conflicting_character_tag,
                conflicting_character_confidence=image.conflicting_character_confidence,
                identity_reasons=parse_json_reason_list(image.identity_reasons),
                suggested_multicolor_tags=parse_json_reason_list(image.suggested_multicolor_tags),
            )
            for image in images
        ],
    )


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
