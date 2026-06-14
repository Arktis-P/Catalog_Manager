from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


SERIES_STATUSES = [
    "pending",
    "collecting",
    "collected",
    "generating",
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
    created_at: datetime
    updated_at: datetime


class SeriesListResponse(BaseModel):
    items: list[SeriesResponse]
    total: int
