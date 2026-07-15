from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CharacterSeriesLinkResponse(BaseModel):
    series_id: int | None
    series_tag: str | None
    copyright_tag: str
    relevance_rank: int
    is_primary: bool
    is_auto: bool
    is_user_edited: bool


class GlobalCharacterResponse(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    collect_status: str
    appearance_status: str
    gender_status: str
    series_status: str
    multi_color_hair: str | None
    hair_color: str | None
    hair_shape: str | None
    eye_color: str | None
    feature_tags: str | None
    gender: str | None
    error_message: str | None
    retry_count: int
    last_collected_at: datetime | None
    primary_series_tag: str | None
    related_series_count: int
    series_links: list[CharacterSeriesLinkResponse]
    image_count: int
    has_cover_image: bool
    parent_character_id: int | None
    parent_character_tag: str | None
    parent_display_name: str | None
    is_alternative: bool
    child_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, character) -> "GlobalCharacterResponse":
        links = sorted(character.series_links, key=lambda link: link.relevance_rank)
        primary = next((link for link in links if link.is_primary), links[0] if links else None)
        primary_tag = None
        if primary is not None:
            primary_tag = primary.series.series_tag if primary.series else primary.copyright_tag
        review = character.review
        parent = character.parent
        return cls(
            id=character.id,
            character_tag=character.character_tag,
            display_name=character.display_name,
            post_count=character.post_count,
            collect_status=character.collect_status,
            appearance_status=character.appearance_status,
            gender_status=character.gender_status,
            series_status=character.series_status,
            multi_color_hair=character.multi_color_hair,
            hair_color=character.hair_color,
            hair_shape=character.hair_shape,
            eye_color=character.eye_color,
            feature_tags=character.feature_tags,
            gender=character.gender,
            error_message=character.error_message,
            retry_count=character.retry_count,
            last_collected_at=character.last_collected_at,
            primary_series_tag=primary_tag,
            related_series_count=len(links),
            image_count=len(character.images),
            has_cover_image=bool(review and review.cover_image_id is not None),
            parent_character_id=character.parent_character_id,
            parent_character_tag=parent.character_tag if parent else None,
            parent_display_name=parent.display_name if parent else None,
            is_alternative=character.parent_character_id is not None,
            child_count=len(character.children),
            series_links=[
                CharacterSeriesLinkResponse(
                    series_id=link.series_id,
                    series_tag=link.series.series_tag if link.series else None,
                    copyright_tag=link.copyright_tag,
                    relevance_rank=link.relevance_rank,
                    is_primary=link.is_primary,
                    is_auto=link.is_auto,
                    is_user_edited=link.is_user_edited,
                )
                for link in links
            ],
            created_at=character.created_at,
            updated_at=character.updated_at,
        )


class GlobalCharacterListResponse(BaseModel):
    items: list[GlobalCharacterResponse]
    total: int


class CatalogListStartRequest(BaseModel):
    min_post_count: int = Field(default=10, ge=0)
    restart: bool = False
    only_new: bool = False


class CharacterCreateRequest(BaseModel):
    character_tag: str = Field(..., min_length=1)


class CatalogTagsStartRequest(BaseModel):
    character_ids: list[int] = Field(..., min_length=1)


class CatalogRetryFailedRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)


class CatalogCollectAllRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=200000)
    chunk_size: int = Field(default=5000, ge=1, le=5000)


class CatalogJobResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    phase: str
    message: str
    current: int
    total: int
    created: int
    updated: int
    success_count: int
    partial_count: int
    failed_count: int
    current_character_tag: str
    active_items: list[str]
    error: str | None
    started_at: str
    finished_at: str | None

    @classmethod
    def from_state(cls, state) -> "CatalogJobResponse":
        return cls(
            job_id=state.job_id,
            job_type=state.job_type,
            status=state.status,
            phase=state.phase,
            message=state.message,
            current=state.current,
            total=state.total,
            created=state.created,
            updated=state.updated,
            success_count=state.success_count,
            partial_count=state.partial_count,
            failed_count=state.failed_count,
            current_character_tag=state.current_character_tag,
            active_items=list(state.active_items),
            error=state.error,
            started_at=state.started_at,
            finished_at=state.finished_at,
        )


class CatalogJobListResponse(BaseModel):
    items: list[CatalogJobResponse]


class CharacterLinkCandidate(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int = 0
    similarity_score: float = 0.0
    linkable: bool = True
    review_status: str | None = None
    rating: int | None = None
    image_count: int = 0
    # completed 항목의 카탈로그 커버 이미지 경로. 클릭 시 미리보기 팝업에 사용한다.
    cover_image_path: str | None = None


class CharacterLinkCandidateListResponse(BaseModel):
    items: list[CharacterLinkCandidate]


class CharacterLinkRequest(BaseModel):
    parent_character_id: int = Field(ge=1)


class CharacterLinkResponse(BaseModel):
    child_id: int
    child_character_tag: str
    parent_id: int
    parent_character_tag: str


class CharacterUnlinkResponse(BaseModel):
    child_id: int
    child_character_tag: str
    parent_id: int
    parent_character_tag: str


class GlobalCharacterImageResponse(BaseModel):
    id: int
    image_path: str
    is_cover: bool
    auto_status: str | None = None


class GlobalCharacterImagesResponse(BaseModel):
    id: int
    images: list[GlobalCharacterImageResponse]
