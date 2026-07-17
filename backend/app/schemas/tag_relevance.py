from datetime import datetime

from pydantic import BaseModel, Field


class RelevanceCollectStartRequest(BaseModel):
    character_ids: list[int] | None = Field(default=None)


class RelevanceCollectError(BaseModel):
    character_id: int
    character_tag: str
    error: str


class RelevanceCollectJobResponse(BaseModel):
    job_id: str
    status: str
    phase: str
    message: str
    current: int
    total: int
    success_count: int
    error_count: int
    current_character_tag: str
    errors: list[RelevanceCollectError]
    started_at: str
    finished_at: str | None = None

    @classmethod
    def from_state(cls, state) -> "RelevanceCollectJobResponse":
        return cls(
            job_id=state.job_id,
            status=state.status,
            phase=state.phase,
            message=state.message,
            current=state.current,
            total=state.total,
            success_count=state.success_count,
            error_count=state.error_count,
            current_character_tag=state.current_character_tag,
            errors=state.errors,
            started_at=state.started_at,
            finished_at=state.finished_at,
        )


class AppearanceTagRelevanceResponse(BaseModel):
    id: int
    global_character_id: int
    tag: str
    tag_category: str
    cooccurrence_count: int
    character_post_count: int
    relevance_score: float
    is_prompt_candidate: bool
    is_confirmed: bool
    collected_at: datetime | None = None

    model_config = {"from_attributes": True}


class AppearanceTagRelevanceListResponse(BaseModel):
    items: list[AppearanceTagRelevanceResponse]
