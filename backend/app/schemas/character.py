from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


CHARACTER_STATUSES = [
    "confirmed",
    "needs_check",
    "excluded",
    "tag_needs_check",
    "ready_for_generation",
]

CATALOG_STATUSES = [
    "completed",
    "needs_review",
    "needs_regen",
    "missing_image",
    "tag_needs_check",
    "excluded",
    "generation_unstable",
]


class CharacterBase(BaseModel):
    character_tag: str
    display_name: str = ""
    danbooru_url: str | None = None
    post_count: int = 0
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    status: str = "needs_check"


class CharacterSeriesUpdate(BaseModel):
    series_id: int = Field(ge=1)


class CharacterResponse(CharacterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int
    series_tag: str = ""
    series_display_name: str = ""
    gender: str | None = None
    generation_prompt: str | None = None
    appearance_confirmed: bool = False
    source_series_id: int | None = None
    source_series_tag: str | None = None
    from_wiki: bool = False
    from_list_page: bool = False
    from_posts: bool = False
    from_related: bool = False
    needs_check_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class CharacterListResponse(BaseModel):
    items: list[CharacterResponse]
    total: int


class ReviewSummary(BaseModel):
    gender: str | None = None
    type: str | None = None
    rating: int | None = None
    final_prompt: str | None = None
    review_status: str | None = None


class CatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int
    series_tag: str
    series_display_name: str
    character_tag: str
    display_name: str
    post_count: int = 0
    danbooru_url: str | None = None
    cover_image: str | None = None
    gender: str | None = None
    type: str | None = None
    rating: int | None = None
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    generation_prompt: str | None = None
    final_prompt: str | None = None
    character_status: str
    catalog_status: str
    has_cover_image: bool = False
    needs_review: bool = False
    needs_regen: bool = False


class CatalogListResponse(BaseModel):
    items: list[CatalogItemResponse]
    total: int


class GlobalCatalogItemResponse(BaseModel):
    """'캐릭터 목록'(GlobalCharacter) 리뷰 완료 결과를 카탈로그 탭에 노출하기 위한 항목.
    시리즈가 아직 연결되지 않았을 수 있어 series_id/series_tag는 비어 있을 수 있다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int | None = None
    series_tag: str = ""
    series_display_name: str = ""
    character_tag: str
    display_name: str
    post_count: int = 0
    danbooru_url: str | None = None
    cover_image: str | None = None
    gender: str | None = None
    type: str | None = None
    rating: int | None = None
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    generation_prompt: str | None = None
    final_prompt: str | None = None
    character_status: str
    catalog_status: str
    has_cover_image: bool = False
    needs_review: bool = False
    needs_regen: bool = False


class GlobalCatalogListResponse(BaseModel):
    items: list[GlobalCatalogItemResponse]
    total: int


class CatalogItemUpdateRequest(BaseModel):
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    gender: str | None = None
    rating: int | None = Field(default=None, ge=-1, le=6)
    type: str | None = None
    final_prompt: str | None = None


CATALOG_EXPORT_COLUMNS = [
    "series_tag",
    "series_display_name",
    "character_tag",
    "display_name",
    "post_count",
    "catalog_status",
    "character_status",
    "gender",
    "type",
    "rating",
    "hair_color",
    "multi_color_hair",
    "hair_shape",
    "eye_color",
    "feature_tags",
    "generation_prompt",
    "final_prompt",
    "cover_image",
    "danbooru_url",
]


class CatalogFilters(BaseModel):
    series_tag: str | None = None
    rating: int | None = Field(default=None, ge=-1, le=6)
    gender: str | None = None
    type: str | None = None
    hair_color: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None
    status: str | None = None
    has_cover_image: bool | None = None
    needs_review: bool | None = None
    needs_regen: bool | None = None
    search: str | None = None
