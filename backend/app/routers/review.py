from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.schemas.generation import GenerationJobState
from app.schemas.review import (
    AppearanceReviewConfirmResponse,
    AppearanceReviewItemResponse,
    AppearanceReviewListResponse,
    AppearanceReviewUpdateRequest,
    CatalogReviewCompleteRequest,
    CatalogReviewCompleteResponse,
    CatalogReviewImageResponse,
    CatalogReviewItemResponse,
    CatalogReviewListResponse,
    CatalogReviewUndoResponse,
)
from app.services.generation_job_manager import generation_job_manager
from app.services.review_service import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


def _to_appearance_item(character) -> AppearanceReviewItemResponse:
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
        gender=normalize_gender(character.gender),
        generation_prompt=character.generation_prompt,
        appearance_confirmed=character.appearance_confirmed,
    )


def _visible_images(character) -> list:
    return sorted(
        [image for image in character.images if not image.is_rejected],
        key=lambda image: image.created_at,
    )[:4]


def _to_catalog_item(character) -> CatalogReviewItemResponse:
    series = character.series
    review = character.review
    images = _visible_images(character)
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
        gender=normalize_gender(character.gender),
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
        items=[_to_appearance_item(character) for character in items],
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
            gender=payload.gender,
        )
        return _to_appearance_item(character)
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


@router.get("/catalog", response_model=CatalogReviewListResponse)
def list_catalog_reviews(
    series_id: int = Query(..., ge=1),
    filter_status: str = Query(default="pending", pattern="^(pending|completed|all)$"),
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    service: ReviewService = Depends(get_review_service),
):
    try:
        series, items, total = service.list_catalog_reviews(
            series_id=series_id,
            filter_status=filter_status,
            search=search,
            skip=skip,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CatalogReviewListResponse(
        items=[_to_catalog_item(character) for character in items],
        total=total,
        series_id=series.id,
        series_tag=series.series_tag,
    )


@router.post("/catalog/{character_id}/complete", response_model=CatalogReviewCompleteResponse)
def complete_catalog_review(
    character_id: int,
    payload: CatalogReviewCompleteRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.complete_catalog_review(
            character_id,
            cover_image_id=payload.cover_image_id,
            gender=payload.gender,
            rating=payload.rating,
            final_prompt=payload.final_prompt,
        )
        review = character.review
        return CatalogReviewCompleteResponse(
            id=character.id,
            review_status=review.review_status if review else "pending",
            cover_image_id=review.cover_image_id if review else None,
            gender=normalize_gender(review.gender) if review else None,
            rating=review.rating if review else None,
            final_prompt=review.final_prompt if review else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/catalog/{character_id}/undo", response_model=CatalogReviewUndoResponse)
def undo_catalog_review(
    character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.undo_catalog_review(character_id)
        review = character.review
        return CatalogReviewUndoResponse(
            id=character.id,
            review_status=review.review_status if review else "pending",
            cover_image_id=review.cover_image_id if review else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/catalog/{character_id}/regenerate", response_model=GenerationJobState)
def regenerate_catalog_character(
    character_id: int,
    prompt_level: int = Query(default=1, ge=1, le=5),
    service: ReviewService = Depends(get_review_service),
):
    character = service.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    job = generation_job_manager.start_generation(
        character.series_id,
        character_ids=[character.id],
        prompt_level=prompt_level,
        require_confirmed=False,
    )
    return GenerationJobState(
        job_id=job.job_id,
        series_id=job.series_id,
        series_tag=job.series_tag,
        queue_id=job.queue_id,
        job_type=job.job_type,
        status=job.status,
        phase=job.phase,
        message=job.message,
        current=job.current,
        total=job.total,
        completed=job.completed,
        failed=job.failed,
        prompt_level=job.prompt_level,
        current_character_tag=job.current_character_tag,
        last_image_path=job.last_image_path,
        auto_pass=job.auto_pass,
        auto_warning=job.auto_warning,
        auto_reject=job.auto_reject,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
