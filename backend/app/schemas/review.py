from __future__ import annotations

from pydantic import BaseModel, Field


class AppearanceReviewItemResponse(BaseModel):
    id: int
    series_tag: str
    series_display_name: str
    character_tag: str
    display_name: str
    post_count: int
    danbooru_url: str | None = None
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None
    generation_prompt: str | None = None
    appearance_confirmed: bool = False


class AppearanceReviewListResponse(BaseModel):
    items: list[AppearanceReviewItemResponse]
    total: int


class AppearanceReviewUpdateRequest(BaseModel):
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None


class AppearanceReviewConfirmResponse(BaseModel):
    id: int
    appearance_confirmed: bool
    generation_prompt: str | None = None


class CatalogReviewImageResponse(BaseModel):
    id: int
    image_path: str
    auto_status: str | None = None
    cover_score: float | None = None
    hair_match: bool | None = None
    eye_match: bool | None = None
    gender_pred: str | None = None
    is_rejected: bool = False
    is_cover: bool = False
    # V2 자동 검사 (quality/identity 분리, §6·§8) — GlobalCharacterImage에서만 채워진다.
    is_provisional: bool = False
    quality_status: str | None = None
    quality_score: float | None = None
    quality_reasons: list[str] = Field(default_factory=list)
    identity_status: str | None = None
    character_confidence: float | None = None
    hair_color_confidence: float | None = None
    conflicting_character_tag: str | None = None
    conflicting_character_confidence: float | None = None
    identity_reasons: list[str] = Field(default_factory=list)
    suggested_multicolor_tags: list[str] = Field(default_factory=list)


class CatalogReviewItemResponse(BaseModel):
    id: int
    series_tag: str
    series_display_name: str
    character_tag: str
    display_name: str
    post_count: int
    danbooru_url: str | None = None
    danbooru_wiki_url: str | None = None
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None
    generation_prompt: str | None = None
    character_status: str
    needs_check_reason: str | None = None
    review_status: str | None = None
    rating: int | None = None
    type: str | None = None
    final_prompt: str | None = None
    cover_image_id: int | None = None
    images: list[CatalogReviewImageResponse] = Field(default_factory=list)


class CatalogReviewListResponse(BaseModel):
    items: list[CatalogReviewItemResponse]
    total: int
    series_id: int
    series_tag: str


class CatalogReviewCompleteRequest(BaseModel):
    cover_image_id: int | None = None
    gender: str | None = None
    rating: int | None = Field(default=None, ge=-1, le=6)
    final_prompt: str | None = None
    selected_tags: str | None = None


class V2ReviewSaveRequest(BaseModel):
    cover_image_id: int | None = None
    gender: str | None = None
    rating: int | None = Field(default=None, ge=-1, le=6)
    base_prompt: str | None = None
    selected_tags: str | None = None


class CatalogReviewCompleteResponse(BaseModel):
    id: int
    review_status: str
    cover_image_id: int | None = None
    gender: str | None = None
    rating: int | None = None
    final_prompt: str | None = None


class CatalogReviewUndoResponse(BaseModel):
    id: int
    review_status: str
    cover_image_id: int | None = None


class CatalogReviewDismissNeedsCheckResponse(BaseModel):
    id: int
    character_status: str
    needs_check_reason: str | None = None


class CatalogReviewPurgeUnselectedResponse(BaseModel):
    id: int
    removed_count: int
    item: CatalogReviewItemResponse


class GlobalCatalogReviewPurgeUnselectedResponse(BaseModel):
    id: int
    removed_count: int
    item: GlobalCatalogReviewItemResponse


class CatalogReviewPurgeUnselectedBulkResponse(BaseModel):
    affected_count: int
    removed_count: int


class CatalogReviewRegenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    gender: str | None = None


class ReviewRegenerateJobResponse(BaseModel):
    job_id: str
    character_id: int
    character_tag: str
    series_tag: str = ""
    scope: str = "series"
    status: str
    phase: str
    message: str
    current: int = 0
    total: int = 0
    error: str | None = None
    result: CatalogReviewItemResponse | GlobalCatalogReviewItemResponse | None = None
    started_at: str
    finished_at: str | None = None


class ReviewRegenerateJobListResponse(BaseModel):
    items: list[ReviewRegenerateJobResponse]


class CatalogReviewRegenerateResponse(ReviewRegenerateJobResponse):
    pass


class GlobalCatalogReviewItemResponse(BaseModel):
    """캐릭터 목록(GlobalCharacter) 중심 리뷰 항목. CatalogReviewItemResponse와 필드가 동일하도록
    맞춰 프론트엔드에서 CatalogReviewRow 컴포넌트를 그대로 재사용할 수 있게 한다."""

    id: int
    series_tag: str = ""
    series_display_name: str = ""
    character_tag: str
    display_name: str
    post_count: int
    danbooru_url: str | None = None
    danbooru_wiki_url: str | None = None
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None
    generation_prompt: str | None = None
    character_status: str = ""
    needs_check_reason: str | None = None
    review_status: str | None = None
    rating: int | None = None
    type: str | None = None
    final_prompt: str | None = None
    cover_image_id: int | None = None
    parent_character_tag: str | None = None
    parent_display_name: str | None = None
    is_alternative: bool = False
    child_count: int = 0
    images: list[CatalogReviewImageResponse] = Field(default_factory=list)


class GlobalCatalogReviewListResponse(BaseModel):
    items: list[GlobalCatalogReviewItemResponse]
    total: int


class V2ReviewImageResponse(BaseModel):
    id: int
    image_path: str
    auto_status: str | None = None
    cover_score: float | None = None
    hair_match: bool | None = None
    eye_match: bool | None = None
    gender_pred: str | None = None
    quality_status: str | None = None
    quality_score: float | None = None
    quality_reasons: str | None = None
    identity_status: str | None = None
    character_confidence: float | None = None
    hair_color_confidence: float | None = None
    conflicting_character_tag: str | None = None
    conflicting_character_confidence: float | None = None
    identity_reasons: str | None = None
    suggested_multicolor_tags: list[str] = Field(default_factory=list)
    is_provisional: bool = False
    is_rejected: bool = False
    is_cover: bool = False


class V2ReviewCharacterResponse(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    danbooru_wiki_url: str | None = None
    series_ids: list[int] = Field(default_factory=list)
    series_tags: list[str] = Field(default_factory=list)
    is_alternative: bool = False
    parent_character_id: int | None = None
    parent_character_tag: str | None = None
    parent_display_name: str | None = None
    child_count: int = 0
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None
    primary_hair_color: str | None = None
    primary_hair_needs_review: bool = False
    base_prompt: str | None = None
    previous_base_prompt: str | None = None
    prompt_modified: bool = False
    first_post_at: str | None = None
    generation_status: str
    generation_attempts: int = 0
    review_status: str = "pending"
    rating: int | None = None
    rating_stage: str = "primary"
    selected_tags: str | None = None
    cover_image_id: int | None = None
    preview_image: V2ReviewImageResponse | None = None
    images: list[V2ReviewImageResponse] = Field(default_factory=list)


class V2ReviewCharacterListResponse(BaseModel):
    items: list[V2ReviewCharacterResponse]
    total: int


class V2ReviewCompleteResponse(BaseModel):
    id: int
    review_status: str
    rating: int | None = None
    rating_stage: str = "primary"
    gender: str | None = None
    base_prompt: str | None = None
    previous_base_prompt: str | None = None
    selected_tags: str | None = None


class V2ReviewStatsResponse(BaseModel):
    total: int
    pending: int = 0
    in_progress: int = 0
    completed: int = 0


class V2BulkCompleteItemRequest(BaseModel):
    character_id: int
    rating: int | None = Field(default=None, ge=-1, le=6)
    gender: str | None = None
    base_prompt: str | None = None
    selected_tags: str | None = None
    cover_image_id: int | None = None


class V2BulkCompleteRequest(BaseModel):
    items: list[V2BulkCompleteItemRequest] = Field(min_length=1, max_length=100)


class V2BulkCompleteItemResult(BaseModel):
    character_id: int
    status: str
    error: str | None = None


class V2BulkCompleteResponse(BaseModel):
    completed: int
    skipped: int
    failed: int
    results: list[V2BulkCompleteItemResult]


class ReviewPipelineImageResponse(BaseModel):
    id: int
    image_path: str
    is_cover: bool = False
    is_rejected: bool = False
    auto_status: str | None = None
    quality_status: str | None = None
    identity_status: str | None = None
    cover_score: float | None = None


class ParentChildCandidateResponse(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    review_status: str = "pending"
    rating: int | None = None
    gender: str | None = None
    generation_status: str = "not_generated"
    parent_character_id: int | None = None
    parent_character_tag: str | None = None
    child_count: int = 0
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    primary_hair_color: str | None = None
    reasons: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    default_selected: bool = False
    already_linked: bool = False
    preview_image: ReviewPipelineImageResponse | None = None


class ParentChildGroupResponse(BaseModel):
    group_id: str
    parent: ParentChildCandidateResponse
    children: list[ParentChildCandidateResponse] = Field(default_factory=list)
    candidate_count: int = 0
    selected_count: int = 0
    conflict_count: int = 0
    reasons: list[str] = Field(default_factory=list)


class ParentChildGroupListResponse(BaseModel):
    items: list[ParentChildGroupResponse]
    total: int


class ParentChildApplyRequest(BaseModel):
    selected_child_ids: list[int] = Field(default_factory=list, max_length=100)
    unlink_child_ids: list[int] = Field(default_factory=list, max_length=100)
    inherit_tags: bool = True
    apply_parent_rating: bool = False
    complete_children: bool = False
    complete_parent: bool = False


class ParentChildApplyConflict(BaseModel):
    child_id: int
    field: str
    parent_value: str | None = None
    child_value: str | None = None


class ParentChildApplyResponse(BaseModel):
    parent_id: int
    linked_child_ids: list[int] = Field(default_factory=list)
    unlinked_child_ids: list[int] = Field(default_factory=list)
    inherited_fields: dict[int, list[str]] = Field(default_factory=dict)
    conflicts: list[ParentChildApplyConflict] = Field(default_factory=list)
    completed_child_ids: list[int] = Field(default_factory=list)
    parent_completed: bool = False


class ParentChildDismissRequest(BaseModel):
    candidate_id: int = Field(ge=1)
    reason: str | None = None


class ParentChildDismissResponse(BaseModel):
    group_id: str
    candidate_id: int
    dismissed: bool = True
    unlinked: bool = False


class DanbooruReferenceImageResponse(BaseModel):
    post_id: int
    preview_url: str | None = None
    sample_url: str | None = None
    file_url: str | None = None
    width: int | None = None
    height: int | None = None
    rating: str | None = None
    post_url: str


class DanbooruReferenceImageListResponse(BaseModel):
    character_id: int
    character_tag: str
    images: list[DanbooruReferenceImageResponse] = Field(default_factory=list)
    source: str = "recent_posts"
    error: str | None = None


class NonHumanCandidateResponse(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    score: float
    reasons: list[str] = Field(default_factory=list)
    classifier_version: str
    review_status: str = "pending"
    current_rating: int | None = None
    non_human_review_result: str | None = None
    gender: str | None = None
    generation_status: str = "not_generated"
    series_tags: list[str] = Field(default_factory=list)
    related_tags: list[str] = Field(default_factory=list)
    preview_image: ReviewPipelineImageResponse | None = None


class NonHumanCandidateListResponse(BaseModel):
    items: list[NonHumanCandidateResponse]
    total: int


class NonHumanDecisionRequest(BaseModel):
    result: str = Field(pattern="^(non_human|generation_unavailable|human_female|general_review)$")
    complete_review: bool = True
    overwrite_existing: bool = False
    reopen_completed: bool = False


class NonHumanDecisionResponse(BaseModel):
    id: int
    result: str
    review_status: str
    rating: int | None = None
    non_human_review_result: str | None = None
