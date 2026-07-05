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
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, character) -> "GlobalCharacterResponse":
        links = sorted(character.series_links, key=lambda link: link.relevance_rank)
        primary = next((link for link in links if link.is_primary), links[0] if links else None)
        primary_tag = None
        if primary is not None:
            primary_tag = primary.series.series_tag if primary.series else primary.copyright_tag
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
