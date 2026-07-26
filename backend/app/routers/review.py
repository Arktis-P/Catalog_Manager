from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.schemas.review import (
    AppearanceReviewConfirmResponse,
    AppearanceReviewItemResponse,
    AppearanceReviewListResponse,
    AppearanceReviewUpdateRequest,
    CatalogReviewCompleteRequest,
    CatalogReviewCompleteResponse,
    CatalogReviewDismissNeedsCheckResponse,
    CatalogReviewItemResponse,
    CatalogReviewListResponse,
    CatalogReviewPurgeUnselectedBulkResponse,
    CatalogReviewPurgeUnselectedResponse,
    CatalogReviewRegenerateRequest,
    CatalogReviewRegenerateResponse,
    CatalogReviewUndoResponse,
    GlobalCatalogReviewItemResponse,
    GlobalCatalogReviewListResponse,
    GlobalCatalogReviewPurgeUnselectedResponse,
    DanbooruReferenceImageListResponse,
    DanbooruReferenceImageResponse,
    NonHumanCandidateListResponse,
    NonHumanCandidateResponse,
    NonHumanDecisionRequest,
    NonHumanDecisionResponse,
    ParentChildApplyConflict,
    ParentChildApplyRequest,
    ParentChildApplyResponse,
    ParentChildCandidateResponse,
    ParentChildDismissRequest,
    ParentChildDismissResponse,
    ParentChildGroupListResponse,
    ParentChildGroupResponse,
    ReviewPipelineImageResponse,
    V2BulkCompleteItemResult,
    V2BulkCompleteRequest,
    V2BulkCompleteResponse,
    V2ReviewCharacterListResponse,
    V2ReviewCharacterResponse,
    V2ReviewCompleteResponse,
    V2ReviewImageResponse,
    V2ReviewSaveRequest,
    V2ReviewStatsResponse,
    ReviewRegenerateJobListResponse,
    ReviewRegenerateJobResponse,
)
from app.services.review_pipeline_service import (
    NON_HUMAN_CLASSIFIER_VERSION,
    ReviewPipelineService,
)
from app.services.review_catalog_serializer import (
    parse_json_reason_list,
    to_catalog_item,
    to_catalog_item_global,
)
from app.services.review_regenerate_job_manager import (
    ReviewRegenerateJobState,
    review_regenerate_job_manager,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


def get_review_pipeline_service(db: Session = Depends(get_db)) -> ReviewPipelineService:
    return ReviewPipelineService(db)


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


def _to_catalog_item(character) -> CatalogReviewItemResponse:
    return to_catalog_item(character)


def _to_v2_review_image(image) -> V2ReviewImageResponse:
    return V2ReviewImageResponse(
        id=image.id,
        image_path=image.image_path,
        auto_status=image.auto_status,
        cover_score=image.cover_score,
        hair_match=image.hair_match,
        eye_match=image.eye_match,
        gender_pred=image.gender_pred,
        quality_status=image.quality_status,
        quality_score=image.quality_score,
        quality_reasons=image.quality_reasons,
        identity_status=image.identity_status,
        character_confidence=image.character_confidence,
        hair_color_confidence=image.hair_color_confidence,
        conflicting_character_tag=image.conflicting_character_tag,
        conflicting_character_confidence=image.conflicting_character_confidence,
        identity_reasons=image.identity_reasons,
        suggested_multicolor_tags=parse_json_reason_list(image.suggested_multicolor_tags),
        is_provisional=image.is_provisional,
        is_rejected=image.is_rejected,
        is_cover=image.is_cover,
    )


def _to_v2_review_character(character) -> V2ReviewCharacterResponse:
    review = character.review
    visible_images = sorted(
        [image for image in character.images if not image.is_rejected],
        key=lambda image: (not image.is_cover, -(image.cover_score or 0), image.id),
    )
    preview_image = visible_images[0] if visible_images else None
    series_links = [link for link in character.series_links if link.series_id is not None]
    return V2ReviewCharacterResponse(
        id=character.id,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        danbooru_wiki_url=ReviewService.build_wiki_url(character.character_tag),
        series_ids=[link.series_id for link in series_links],
        series_tags=[link.series.series_tag for link in series_links if link.series],
        **ReviewService.merge_status_fields(character),
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        gender=normalize_gender(review.gender if review and review.gender else character.gender),
        primary_hair_color=character.primary_hair_color,
        primary_hair_needs_review=character.primary_hair_needs_review,
        base_prompt=character.base_prompt,
        previous_base_prompt=character.previous_base_prompt,
        prompt_modified=bool(
            character.previous_base_prompt is not None and character.base_prompt != character.previous_base_prompt
        ),
        first_post_at=character.first_post_at.isoformat() if character.first_post_at else None,
        generation_status=character.generation_status,
        generation_attempts=character.generation_attempts,
        review_status=review.review_status if review else "pending",
        rating=review.rating if review else None,
        rating_stage=review.rating_stage if review else "primary",
        selected_tags=review.selected_tags if review else None,
        cover_image_id=review.cover_image_id if review else None,
        preview_image=_to_v2_review_image(preview_image) if preview_image else None,
        images=[_to_v2_review_image(image) for image in visible_images],
    )


def _to_pipeline_image(image) -> ReviewPipelineImageResponse | None:
    if image is None:
        return None
    return ReviewPipelineImageResponse(**image.__dict__)


def _to_parent_child_candidate(item) -> ParentChildCandidateResponse:
    character = item.character
    review = character.review
    parent = character.parent
    return ParentChildCandidateResponse(
        id=character.id,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        review_status=review.review_status if review else "pending",
        rating=review.rating if review else None,
        gender=normalize_gender(review.gender if review and review.gender else character.gender),
        generation_status=character.generation_status,
        parent_character_id=character.parent_character_id,
        parent_character_tag=parent.character_tag if parent else None,
        child_count=len(character.children),
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        primary_hair_color=character.primary_hair_color,
        reasons=item.reasons,
        confidence=item.confidence,
        default_selected=item.default_selected,
        already_linked=item.already_linked,
        preview_image=_to_pipeline_image(ReviewPipelineService.preview_image(character)),
    )


def _to_parent_child_group(group) -> ParentChildGroupResponse:
    return ParentChildGroupResponse(
        group_id=group.group_id,
        parent=_to_parent_child_candidate(group.parent),
        children=[_to_parent_child_candidate(child) for child in group.children],
        candidate_count=len(group.children),
        selected_count=sum(1 for child in group.children if child.default_selected),
        conflict_count=group.conflict_count,
        reasons=group.reasons,
    )


def _to_non_human_candidate(item) -> NonHumanCandidateResponse:
    character = item.character
    review = character.review
    series_tags = [link.copyright_tag for link in character.series_links]
    return NonHumanCandidateResponse(
        id=character.id,
        character_tag=character.character_tag,
        display_name=character.display_name or character.character_tag,
        post_count=character.post_count,
        score=item.score,
        reasons=item.reasons,
        classifier_version=NON_HUMAN_CLASSIFIER_VERSION,
        review_status=review.review_status if review else "pending",
        current_rating=review.rating if review else None,
        non_human_review_result=review.non_human_review_result if review else None,
        gender=normalize_gender(review.gender if review and review.gender else character.gender),
        generation_status=character.generation_status,
        series_tags=series_tags,
        related_tags=item.related_tags,
        preview_image=_to_pipeline_image(ReviewPipelineService.preview_image(character)),
    )


def _job_to_response(job: ReviewRegenerateJobState) -> ReviewRegenerateJobResponse:
    result = None
    if job.result:
        result = (
            GlobalCatalogReviewItemResponse(**job.result)
            if job.scope == "global"
            else CatalogReviewItemResponse(**job.result)
        )
    return ReviewRegenerateJobResponse(
        job_id=job.job_id,
        character_id=job.character_id,
        character_tag=job.character_tag,
        series_tag=job.series_tag,
        scope=job.scope,
        status=job.status,
        phase=job.phase,
        message=job.message,
        current=job.current,
        total=job.total,
        error=job.error,
        result=result,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/v2/characters", response_model=V2ReviewCharacterListResponse)
def list_v2_review_characters(
    review_status: str | None = Query(default=None, pattern="^(pending|in_progress|completed|completed_recent)$"),
    rating: str | None = None,
    quality_status: str | None = None,
    identity_status: str | None = None,
    generation_status: str | None = None,
    gender: str | None = None,
    series_id: int | None = Query(default=None, ge=1),
    multicolor: str | None = Query(default=None, pattern="^(has|suggested)$"),
    prompt_modified: bool | None = None,
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    service: ReviewService = Depends(get_review_service),
):
    try:
        items, total = service.list_v2_review_characters(
            review_status=review_status,
            rating=rating,
            quality_status=quality_status,
            identity_status=identity_status,
            generation_status=generation_status,
            gender=gender,
            series_id=series_id,
            multicolor=multicolor,
            prompt_modified=prompt_modified,
            search=search,
            skip=skip,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return V2ReviewCharacterListResponse(
        items=[_to_v2_review_character(character) for character in items],
        total=total,
    )


@router.post("/v2/characters/{character_id}/complete", response_model=V2ReviewCompleteResponse)
def complete_v2_review_character(
    character_id: int,
    payload: V2ReviewSaveRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.save_v2_review_character(
            character_id,
            review_status="completed",
            cover_image_id=payload.cover_image_id,
            gender=payload.gender,
            rating=payload.rating,
            base_prompt=payload.base_prompt,
            selected_tags=payload.selected_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    review = character.review
    return V2ReviewCompleteResponse(
        id=character.id,
        review_status=review.review_status,
        rating=review.rating,
        rating_stage=review.rating_stage,
        gender=normalize_gender(review.gender) if review.gender else None,
        base_prompt=character.base_prompt,
        previous_base_prompt=character.previous_base_prompt,
        selected_tags=review.selected_tags,
    )


@router.post("/v2/characters/{character_id}/save", response_model=V2ReviewCompleteResponse)
@router.patch("/v2/characters/{character_id}", response_model=V2ReviewCompleteResponse)
def save_v2_review_character(
    character_id: int,
    payload: V2ReviewSaveRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.save_v2_review_character(
            character_id,
            review_status="in_progress",
            cover_image_id=payload.cover_image_id,
            gender=payload.gender,
            rating=payload.rating,
            base_prompt=payload.base_prompt,
            selected_tags=payload.selected_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    review = character.review
    return V2ReviewCompleteResponse(
        id=character.id,
        review_status=review.review_status,
        rating=review.rating,
        rating_stage=review.rating_stage,
        gender=normalize_gender(review.gender) if review.gender else None,
        base_prompt=character.base_prompt,
        previous_base_prompt=character.previous_base_prompt,
        selected_tags=review.selected_tags,
    )


@router.post("/v2/bulk-complete", response_model=V2BulkCompleteResponse)
def bulk_complete_v2_review_characters(
    payload: V2BulkCompleteRequest,
    service: ReviewService = Depends(get_review_service),
):
    completed, skipped, failed, results = service.bulk_complete_v2_review_characters(payload.items)
    return V2BulkCompleteResponse(
        completed=completed,
        skipped=skipped,
        failed=failed,
        results=[V2BulkCompleteItemResult(**result) for result in results],
    )


@router.get("/v2/stats", response_model=V2ReviewStatsResponse)
def get_v2_review_stats(service: ReviewService = Depends(get_review_service)):
    return V2ReviewStatsResponse(**service.get_v2_review_stats())


@router.get("/v2/parent-child-groups", response_model=ParentChildGroupListResponse)
def list_parent_child_groups(
    series_id: int | None = Query(default=None, ge=1),
    search: str | None = None,
    confidence: str = Query(default="all", pattern="^(all|medium|high)$"),
    already_linked_only: bool = False,
    unreviewed_first: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    items, total = service.list_parent_child_groups(
        series_id=series_id,
        search=search,
        confidence=confidence,
        already_linked_only=already_linked_only,
        unreviewed_first=unreviewed_first,
        skip=skip,
        limit=limit,
    )
    return ParentChildGroupListResponse(items=[_to_parent_child_group(item) for item in items], total=total)


@router.get("/v2/parent-child-groups/{group_id}", response_model=ParentChildGroupResponse)
def get_parent_child_group(
    group_id: str,
    confidence: str = Query(default="all", pattern="^(all|medium|high)$"),
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    try:
        group = service.get_parent_child_group(int(group_id), confidence=confidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_parent_child_group(group)


@router.post("/v2/parent-child-groups/{group_id}/apply", response_model=ParentChildApplyResponse)
def apply_parent_child_group(
    group_id: str,
    payload: ParentChildApplyRequest,
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    try:
        result = service.apply_parent_child_group(int(group_id), payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ParentChildApplyResponse(
        parent_id=result.parent_id,
        linked_child_ids=result.linked_child_ids,
        unlinked_child_ids=result.unlinked_child_ids,
        inherited_fields=result.inherited_fields,
        conflicts=[ParentChildApplyConflict(**conflict) for conflict in result.conflicts],
        completed_child_ids=result.completed_child_ids,
        parent_completed=result.parent_completed,
    )


@router.post("/v2/parent-child-groups/{group_id}/dismiss-candidate", response_model=ParentChildDismissResponse)
def dismiss_parent_child_candidate(
    group_id: str,
    payload: ParentChildDismissRequest,
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    try:
        unlinked = service.dismiss_parent_child_candidate(int(group_id), payload.candidate_id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ParentChildDismissResponse(group_id=group_id, candidate_id=payload.candidate_id, unlinked=unlinked)


@router.get("/v2/global-characters/{character_id}/danbooru-reference-images", response_model=DanbooruReferenceImageListResponse)
def get_danbooru_reference_images(
    character_id: int,
    limit: int = Query(default=3, ge=1, le=3),
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    try:
        payload = service.get_danbooru_reference_images(character_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DanbooruReferenceImageListResponse(
        character_id=payload["character_id"],
        character_tag=payload["character_tag"],
        images=[DanbooruReferenceImageResponse(**image) for image in payload["images"]],
        source=payload["source"],
        error=payload.get("error"),
    )


@router.get("/v2/non-human-candidates", response_model=NonHumanCandidateListResponse)
def list_non_human_candidates(
    review_filter: str = Query(default="unreviewed", pattern="^(unreviewed|reviewed|general_review|all)$"),
    category: str | None = None,
    series_id: int | None = Query(default=None, ge=1),
    search: str | None = None,
    include_completed: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    items, total = service.list_non_human_candidates(
        review_filter=review_filter,
        category=category,
        series_id=series_id,
        search=search,
        include_completed=include_completed,
        skip=skip,
        limit=limit,
    )
    return NonHumanCandidateListResponse(items=[_to_non_human_candidate(item) for item in items], total=total)


@router.post("/v2/non-human-candidates/{character_id}/decision", response_model=NonHumanDecisionResponse)
def apply_non_human_decision(
    character_id: int,
    payload: NonHumanDecisionRequest,
    service: ReviewPipelineService = Depends(get_review_pipeline_service),
):
    try:
        character = service.apply_non_human_decision(
            character_id,
            result=payload.result,
            complete_review=payload.complete_review,
            overwrite_existing=payload.overwrite_existing,
            reopen_completed=payload.reopen_completed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    review = character.review
    return NonHumanDecisionResponse(
        id=character.id,
        result=payload.result,
        review_status=review.review_status,
        rating=review.rating,
        non_human_review_result=review.non_human_review_result,
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
    filter_status: str = Query(
        default="pending",
        pattern="^(pending|completed|completed_recent|all|needs_check|triage_fast|triage_check|triage_regen)$",
    ),
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
            selected_tags=payload.selected_tags,
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


@router.post("/catalog/{character_id}/purge-unselected", response_model=CatalogReviewPurgeUnselectedResponse)
def purge_unselected_catalog_images(
    character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character, removed = service.purge_unselected_images(character_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CatalogReviewPurgeUnselectedResponse(
        id=character.id,
        removed_count=removed,
        item=to_catalog_item(character),
    )


@router.post("/catalog/purge-unselected-all", response_model=CatalogReviewPurgeUnselectedBulkResponse)
def purge_unselected_catalog_images_bulk(
    series_id: int = Query(..., ge=1),
    search: str | None = None,
    service: ReviewService = Depends(get_review_service),
):
    affected, removed = service.purge_unselected_images_bulk(series_id, search=search)
    return CatalogReviewPurgeUnselectedBulkResponse(affected_count=affected, removed_count=removed)


@router.post("/catalog/{character_id}/dismiss-needs-check", response_model=CatalogReviewDismissNeedsCheckResponse)
def dismiss_catalog_needs_check(
    character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.dismiss_needs_check(character_id)
        return CatalogReviewDismissNeedsCheckResponse(
            id=character.id,
            character_status=character.status,
            needs_check_reason=character.needs_check_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/catalog/{character_id}/regenerate", response_model=CatalogReviewRegenerateResponse)
def regenerate_catalog_character(
    character_id: int,
    payload: CatalogReviewRegenerateRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        job = service.regenerate_catalog_images(
            character_id,
            prompt=payload.prompt.strip(),
            gender=payload.gender,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _job_to_response(job)


@router.get("/catalog/regenerate/jobs", response_model=ReviewRegenerateJobListResponse)
def list_review_regenerate_jobs():
    jobs = review_regenerate_job_manager.list_visible_jobs()
    return ReviewRegenerateJobListResponse(items=[_job_to_response(job) for job in jobs])


@router.get("/catalog/regenerate/jobs/{job_id}", response_model=ReviewRegenerateJobResponse)
def get_review_regenerate_job(job_id: str):
    job = review_regenerate_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Regenerate job not found")
    return _job_to_response(job)


@router.delete("/catalog/regenerate/jobs/{job_id}")
def dismiss_review_regenerate_job(job_id: str):
    if not review_regenerate_job_manager.dismiss_job(job_id):
        raise HTTPException(status_code=400, detail="완료되지 않은 작업은 지울 수 없습니다")
    return {"ok": True}


# ── 캐릭터 목록(GlobalCharacter) 중심 리뷰 ──────────────────────────────


@router.get("/catalog-global", response_model=GlobalCatalogReviewListResponse)
def list_catalog_reviews_global(
    filter_status: str = Query(default="pending", pattern="^(pending|completed|completed_recent|all)$"),
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    service: ReviewService = Depends(get_review_service),
):
    items, total = service.list_catalog_reviews_global(
        filter_status=filter_status,
        search=search,
        skip=skip,
        limit=limit,
    )
    return GlobalCatalogReviewListResponse(
        items=[to_catalog_item_global(character) for character in items],
        total=total,
    )


@router.post("/catalog-global/{global_character_id}/complete", response_model=CatalogReviewCompleteResponse)
def complete_catalog_review_global(
    global_character_id: int,
    payload: CatalogReviewCompleteRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.complete_catalog_review_global(
            global_character_id,
            cover_image_id=payload.cover_image_id,
            gender=payload.gender,
            rating=payload.rating,
            final_prompt=payload.final_prompt,
            selected_tags=payload.selected_tags,
        )
        review = character.review
        return CatalogReviewCompleteResponse(
            id=character.id,
            review_status=review.review_status if review else "pending",
            cover_image_id=review.cover_image_id if review else None,
            gender=normalize_gender(review.gender) if review and review.gender else None,
            rating=review.rating if review else None,
            final_prompt=review.final_prompt if review else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/catalog-global/{global_character_id}/regenerate", response_model=CatalogReviewRegenerateResponse)
def regenerate_catalog_character_global(
    global_character_id: int,
    payload: CatalogReviewRegenerateRequest,
    service: ReviewService = Depends(get_review_service),
):
    try:
        job = service.regenerate_catalog_images_global(
            global_character_id,
            prompt=payload.prompt.strip(),
            gender=payload.gender,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _job_to_response(job)


@router.post(
    "/catalog-global/{global_character_id}/purge-unselected",
    response_model=GlobalCatalogReviewPurgeUnselectedResponse,
)
def purge_unselected_catalog_images_global(
    global_character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character, removed = service.purge_unselected_images_global(global_character_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GlobalCatalogReviewPurgeUnselectedResponse(
        id=character.id,
        removed_count=removed,
        item=to_catalog_item_global(character),
    )


@router.post("/catalog-global/purge-unselected-all", response_model=CatalogReviewPurgeUnselectedBulkResponse)
def purge_unselected_catalog_images_bulk_global(
    search: str | None = None,
    service: ReviewService = Depends(get_review_service),
):
    affected, removed = service.purge_unselected_images_bulk_global(search=search)
    return CatalogReviewPurgeUnselectedBulkResponse(affected_count=affected, removed_count=removed)


@router.post("/catalog-global/{global_character_id}/undo", response_model=CatalogReviewUndoResponse)
def undo_catalog_review_global(
    global_character_id: int,
    service: ReviewService = Depends(get_review_service),
):
    try:
        character = service.undo_catalog_review_global(global_character_id)
        review = character.review
        return CatalogReviewUndoResponse(
            id=character.id,
            review_status=review.review_status if review else "pending",
            cover_image_id=review.cover_image_id if review else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
