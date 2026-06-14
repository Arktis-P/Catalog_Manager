from pydantic import BaseModel, Field


class CharacterCollectResultResponse(BaseModel):
    series_tag: str
    discovered: int
    created: int
    skipped_existing: int


class CharacterCollectSummaryResponse(BaseModel):
    series_processed: int
    total_discovered: int
    total_created: int
    total_skipped_existing: int
    results: list[CharacterCollectResultResponse]


class CharacterCollectRequest(BaseModel):
    series_id: int | None = None
    series_tag: str | None = None
    status: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
