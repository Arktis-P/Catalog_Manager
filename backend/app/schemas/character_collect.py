from pydantic import BaseModel, Field


class CharacterCollectResultResponse(BaseModel):
    series_tag: str
    discovered: int
    created: int
    skipped_existing: int
    merged_children: int = 0
    skipped_sub_series: list[str] = Field(default_factory=list)
    used_legacy_fallback: bool = False


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


class CollectJobResponse(BaseModel):
    job_id: str
    series_id: int
    series_tag: str
    job_type: str = "character_collect"
    status: str
    phase: str
    message: str
    current: int
    total: int
    discovered: int
    created: int
    skipped_existing: int
    updated: int = 0
    error: str | None = None
    started_at: str
    finished_at: str | None = None

    @classmethod
    def from_state(cls, state) -> "CollectJobResponse":
        return cls(
            job_id=state.job_id,
            series_id=state.series_id,
            series_tag=state.series_tag,
            job_type=getattr(state, "job_type", "character_collect"),
            status=state.status,
            phase=state.phase,
            message=state.message,
            current=state.current,
            total=state.total,
            discovered=state.discovered,
            created=state.created,
            skipped_existing=state.skipped_existing,
            updated=getattr(state, "updated", 0),
            error=state.error,
            started_at=state.started_at,
            finished_at=state.finished_at,
        )


class CollectBatchStartRequest(BaseModel):
    series_ids: list[int] = Field(..., min_length=1)


class CollectJobListResponse(BaseModel):
    items: list[CollectJobResponse]
