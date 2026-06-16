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
    cover_image_id: int
    gender: str | None = None
    rating: int | None = Field(default=None, ge=-1, le=6)
    final_prompt: str | None = None


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
