from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.review import (
    AppearanceReviewConfirmResponse,
    AppearanceReviewItemResponse,
    AppearanceReviewListResponse,
    AppearanceReviewUpdateRequest,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


def _to_review_item(character) -> AppearanceReviewItemResponse:
    series = character.series
    return AppearanceReviewItemResponse(
        id=character.id,
        series_tag=series.series_tag,
        series_display_name=series.display_name,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        danbooru_url=character.danbooru_url,
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        generation_prompt=character.generation_prompt,
        appearance_confirmed=character.appearance_confirmed,
    )


@router.get("/appearance", response_model=AppearanceReviewListResponse)
def list_appearance_reviews(
    series_tag: str | None = None,
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ReviewService = Depends(get_review_service),
):
    items, total = service.list_appearance_reviews(
        series_tag=series_tag,
        search=search,
        skip=skip,
        limit=limit,
    )
    return AppearanceReviewListResponse(
        items=[_to_review_item(character) for character in items],
        total=total,
    )


@router.patch("/appearance/{character_id}", response_model=AppearanceReviewItemResponse)
def update_appearance_review(
    character_id: int,
    payload: AppearanceReviewUpdateRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.update_appearance_draft(
            character_id,
            multi_color_hair=payload.multi_color_hair,
            hair_color=payload.hair_color,
            hair_shape=payload.hair_shape,
            eye_color=payload.eye_color,
            feature_tags=payload.feature_tags,
        )
        return _to_review_item(character)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/appearance/{character_id}/confirm", response_model=AppearanceReviewConfirmResponse)
def confirm_appearance_review(
    character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.confirm_appearance(character_id)
        return AppearanceReviewConfirmResponse(
            id=character.id,
            appearance_confirmed=character.appearance_confirmed,
            generation_prompt=character.generation_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
