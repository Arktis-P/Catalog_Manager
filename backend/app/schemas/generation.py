from __future__ import annotations

from pydantic import BaseModel, Field


class GenerationCandidate(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    generation_prompt: str | None
    appearance_confirmed: bool
    gender: str | None = None
    status: str = "needs_check"
    needs_check_reason: str | None = None


class GenerationCandidateListResponse(BaseModel):
    items: list[GenerationCandidate]
    total: int
    total_characters: int = 0
    with_prompt: int = 0
    confirmed_with_prompt: int = 0
    unconfirmed_with_prompt: int = 0
    needs_check_with_prompt: int = 0


class GenerationStartRequest(BaseModel):
    character_ids: list[int] | None = None
    prompt_level: int = Field(default=1, ge=1, le=5)
    require_confirmed: bool = True


class GenerationPreviewResponse(BaseModel):
    character_id: int
    character_tag: str
    prompt_level: int
    prompt: str
    negative_prompt: str
    prompt_prefix: str = ""
    prompt_suffix: str = ""


class GenerationJobState(BaseModel):
    job_id: str
    series_id: int
    series_tag: str
    queue_id: str
    job_type: str
    status: str
    phase: str
    message: str
    current: int
    total: int
    completed: int
    failed: int
    prompt_level: int
    current_character_tag: str
    last_image_path: str | None = None
    auto_pass: int = 0
    auto_warning: int = 0
    auto_reject: int = 0
    error: str | None = None
    started_at: str
    finished_at: str | None = None


class GenerationJobListResponse(BaseModel):
    items: list[GenerationJobState]


class NaiaStatusResponse(BaseModel):
    configured: bool
    ready: bool
    base_url: str
    portable_dir: str
    wildcards_dir: str
    message: str
    api_mode: str | None = None
    is_generating: bool | None = None


class GenerationQueuePreviewResponse(BaseModel):
    queue_id: str
    series_id: int
    series_tag: str
    prompt_level: int
    character_count: int
    wildcard_path: str
    manifest_path: str
    prompt_template: str
    prompt_prefix: str
    prompt_suffix: str
    negative_prompt: str
    skipped: list[dict[str, object]]


class SuggestLevelResponse(BaseModel):
    suggested_level: int
    breakdown: dict[int, int]


class GlobalGenerationCandidate(BaseModel):
    id: int
    character_tag: str
    display_name: str
    post_count: int
    gender: str | None = None


class GlobalGenerationCandidateListResponse(BaseModel):
    items: list[GlobalGenerationCandidate]
    total: int
    total_completed: int = 0
    already_generated: int = 0
    remaining: int = 0


class GlobalGenerationStartRequest(BaseModel):
    character_ids: list[int] = Field(..., min_length=1, max_length=300)
    prompt_level: int = Field(default=1, ge=1, le=5)
