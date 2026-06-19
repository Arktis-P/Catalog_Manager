from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


SERIES_STATUSES = [
    "pending",
    "collecting",
    "collected",
    "tagged",
    "generating",
    "generated",
    "reviewing",
    "completed",
    "disabled",
]


class SeriesBase(BaseModel):
    series_tag: str = Field(min_length=1, max_length=255)
    display_name: str = Field(default="", max_length=255)
    post_count: int = Field(default=0, ge=0)
    priority: int = Field(default=0)
    status: str = Field(default="pending")
    note: str | None = None


class SeriesCreate(SeriesBase):
    pass


class SeriesUpdate(BaseModel):
    series_tag: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = None
    post_count: int | None = Field(default=None, ge=0)
    priority: int | None = None
    status: str | None = None
    note: str | None = None


class SeriesResponse(SeriesBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_series_id: int | None = None
    parent_series_tag: str | None = None
    character_count: int = 0
    own_character_count: int = 0
    merged_moved_count: int = 0
    merged_duplicate_count: int = 0
    child_count: int = 0
    is_merged_child: bool = False
    last_collect_created: int = 0
    last_collect_skipped: int = 0
    last_appearance_updated: int = 0
    appearance_extracted_count: int = 0
    all_appearance_collected: bool = False
    generation_pipeline_done: bool = False
    created_at: datetime
    updated_at: datetime


class SeriesMergeCandidate(BaseModel):
    id: int
    series_tag: str
    display_name: str
    status: str
    post_count: int = 0
    character_count: int = 0
    similarity_score: float = 0.0
    mergeable: bool = True


class SeriesMergeCandidateListResponse(BaseModel):
    items: list[SeriesMergeCandidate]


class SeriesMergePreviewResponse(BaseModel):
    child_series_id: int
    child_series_tag: str
    parent_series_id: int
    parent_series_tag: str
    child_character_count: int
    duplicate_count: int
    moved_count: int


class SeriesMergeRequest(BaseModel):
    parent_series_id: int = Field(ge=1)


class SeriesMergeResponse(BaseModel):
    child_series_id: int
    child_series_tag: str
    parent_series_id: int
    parent_series_tag: str
    moved_count: int
    duplicate_count: int
    parent_character_count: int


class SeriesUnmergeResponse(BaseModel):
    child_series_id: int
    child_series_tag: str
    moved_back_count: int
    child_character_count: int


class SeriesListResponse(BaseModel):
    items: list[SeriesResponse]
    total: int
