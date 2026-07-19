from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.global_character import GlobalCharacter
from app.schemas.generation import (
    GenerationCandidate,
    GenerationCandidateListResponse,
    GenerationJobListResponse,
    GenerationJobState,
    GenerationPreviewResponse,
    GenerationQueuePreviewResponse,
    GenerationStartRequest,
    GlobalGenerationCandidate,
    GlobalGenerationCandidateListResponse,
    GlobalGenerationStartRequest,
    NaiaStatusResponse,
    SuggestLevelResponse,
    V2GenerationJobListResponse,
    V2GenerationJobState,
    V2GenerationStartRequest,
    V2RegenerateRequest,
)
from app.services.generation_job_manager import generation_job_manager
from app.services.generation_service import GenerationService
from app.services.v2_generation_job_manager import v2_generation_job_manager

router = APIRouter(prefix="/generation", tags=["generation"])


def _job_to_schema(job) -> GenerationJobState:
    return GenerationJobState(
        job_id=job.job_id,
        series_id=job.series_id,
        series_tag=job.series_tag,
        queue_id=job.queue_id,
        job_type=job.job_type,
        status=job.status,
        phase=job.phase,
        message=job.message,
        current=job.current,
        total=job.total,
        completed=job.completed,
        failed=job.failed,
        prompt_level=job.prompt_level,
        current_character_tag=job.current_character_tag,
        last_image_path=job.last_image_path,
        auto_pass=job.auto_pass,
        auto_warning=job.auto_warning,
        auto_reject=job.auto_reject,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _v2_job_to_schema(job) -> V2GenerationJobState:
    return V2GenerationJobState(
        job_id=job.job_id,
        kind=job.kind,
        status=job.status,
        phase=job.phase,
        message=job.message,
        current=job.current,
        total=job.total,
        completed=job.completed,
        failed=job.failed,
        character_tag=job.character_tag,
        current_character_tag=job.current_character_tag,
        character_id=job.character_id,
        generation_status=job.generation_status,
        generation_attempts=job.generation_attempts,
        total_generation_attempts=job.total_generation_attempts,
        prompt_variant_attempts=job.prompt_variant_attempts,
        image_id=job.image_id,
        quality_status=job.quality_status,
        quality_reasons=job.quality_reasons,
        identity_status=job.identity_status,
        identity_reasons=job.identity_reasons,
        is_provisional=job.is_provisional,
        last_failure_reason=job.last_failure_reason,
        errors=job.errors,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/naia/status", response_model=NaiaStatusResponse)
def get_naia_status(db: Session = Depends(get_db)):
    return GenerationService(db).naia_status()


@router.post("/v2/start", response_model=V2GenerationJobState)
def start_v2_generation(payload: V2GenerationStartRequest, db: Session = Depends(get_db)):
    if payload.target in ("selected", "page"):
        character_ids = list(dict.fromkeys(payload.character_ids or []))
        if not character_ids:
            raise HTTPException(status_code=400, detail="character_ids must not be empty")
    elif payload.target == "min_posts":
        if payload.min_post_count is None:
            raise HTTPException(status_code=400, detail="min_post_count is required for min_posts target")
        character_ids = GenerationService(db).list_v2_not_generated_ids(min_post_count=payload.min_post_count)
        if not character_ids:
            raise HTTPException(status_code=404, detail="No characters to generate")
    else:  # "not_generated"
        character_ids = GenerationService(db).list_v2_not_generated_ids()
        if not character_ids:
            raise HTTPException(status_code=404, detail="No characters to generate")

    job = v2_generation_job_manager.start(
        character_ids=character_ids,
        rerun=payload.rerun,
    )
    return _v2_job_to_schema(job)


@router.post("/v2/characters/{character_id}/regenerate", response_model=V2GenerationJobState)
def regenerate_v2_character(
    character_id: int,
    payload: V2RegenerateRequest,
    db: Session = Depends(get_db),
):
    character = db.get(GlobalCharacter, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    job = v2_generation_job_manager.start_regeneration(
        character_id,
        base_prompt=payload.base_prompt,
    )
    if job is None:
        raise HTTPException(status_code=409, detail="Character generation already in progress")
    if not job.character_tag:
        job.character_tag = character.character_tag
    if not job.current_character_tag:
        job.current_character_tag = character.character_tag
    return _v2_job_to_schema(job)


@router.get("/v2/jobs", response_model=V2GenerationJobListResponse)
def list_v2_generation_jobs():
    return V2GenerationJobListResponse(
        items=[_v2_job_to_schema(job) for job in v2_generation_job_manager.list_visible_jobs()]
    )


@router.get("/v2/jobs/{job_id}", response_model=V2GenerationJobState)
def get_v2_generation_job(job_id: str):
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _v2_job_to_schema(job)


@router.post("/v2/jobs/{job_id}/cancel", response_model=V2GenerationJobState)
def cancel_v2_generation_job(job_id: str):
    cancelled = v2_generation_job_manager.cancel(job_id)
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not cancelled and job.status in {"queued", "running", "paused"}:
        raise HTTPException(status_code=409, detail="Job could not be cancelled")
    return _v2_job_to_schema(job)


@router.post("/v2/jobs/{job_id}/pause", response_model=V2GenerationJobState)
def pause_v2_generation_job(job_id: str):
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=400, detail="Only running jobs can be paused")
    v2_generation_job_manager.pause(job_id)
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _v2_job_to_schema(job)


@router.post("/v2/jobs/{job_id}/resume", response_model=V2GenerationJobState)
def resume_v2_generation_job(job_id: str):
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    v2_generation_job_manager.resume(job_id)
    job = v2_generation_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _v2_job_to_schema(job)


@router.get("/characters/candidates", response_model=GlobalGenerationCandidateListResponse)
def list_global_generation_candidates(
    search: str | None = Query(default=None),
    limit: int = Query(default=300, ge=1, le=300),
    db: Session = Depends(get_db),
):
    """캐릭터 목록(GlobalCharacter) 중심 생성 후보: 특징 태그 수집 완료 + 아직 이미지 미생성."""
    service = GenerationService(db)
    items = service.list_generation_candidates_global(search=search, limit=limit)
    stats = service.get_candidate_stats_global()
    return GlobalGenerationCandidateListResponse(
        items=[
            GlobalGenerationCandidate(
                id=character.id,
                character_tag=character.character_tag,
                display_name=character.display_name,
                post_count=character.post_count,
                gender=character.gender,
            )
            for character in items
        ],
        total=len(items),
        **stats,
    )


@router.post("/characters/start", response_model=GenerationJobState)
def start_global_character_generation(payload: GlobalGenerationStartRequest):
    """캐릭터 목록 중심 이미지 생성 시작. 이미 진행 중인 캐릭터 목록 생성 job이 있으면
    새 job은 대기열에 올라가 이전 job이 끝난 뒤 자동으로 시작된다."""
    job = generation_job_manager.start_character_generation(
        payload.character_ids,
        prompt_level=payload.prompt_level,
    )
    return _job_to_schema(job)


@router.get("/series/{series_id}/candidates", response_model=GenerationCandidateListResponse)
def list_generation_candidates(
    series_id: int,
    require_confirmed: bool = Query(default=True),
    exclude_needs_check: bool = Query(default=True),
    needs_check_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    service = GenerationService(db)
    items = service.list_generation_candidates(
        series_id,
        require_confirmed=require_confirmed,
        exclude_needs_check=exclude_needs_check,
        needs_check_only=needs_check_only,
        search=search,
    )
    stats = service.get_candidate_stats(series_id)
    return GenerationCandidateListResponse(
        items=[
            GenerationCandidate(
                id=character.id,
                character_tag=character.character_tag,
                display_name=character.display_name,
                post_count=character.post_count,
                generation_prompt=character.generation_prompt,
                appearance_confirmed=character.appearance_confirmed,
                gender=character.gender,
                status=character.status,
                needs_check_reason=character.needs_check_reason,
            )
            for character in items
        ],
        total=len(items),
        **stats,
    )


@router.get("/characters/{character_id}/preview", response_model=GenerationPreviewResponse)
def preview_generation_prompt(
    character_id: int,
    prompt_level: int = Query(default=1, ge=1, le=5),
    db: Session = Depends(get_db),
):
    service = GenerationService(db)
    try:
        payload = service.preview_prompt(character_id, prompt_level=prompt_level)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GenerationPreviewResponse(**payload)


@router.post("/series/{series_id}/preview-queue", response_model=GenerationQueuePreviewResponse)
def preview_generation_queue(
    series_id: int,
    payload: GenerationStartRequest,
    db: Session = Depends(get_db),
):
    service = GenerationService(db)
    try:
        result = service.prepare_queue(
            series_id,
            character_ids=payload.character_ids,
            prompt_level=payload.prompt_level,
            require_confirmed=payload.require_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenerationQueuePreviewResponse(
        queue_id=str(result["queue_id"]),
        series_id=int(result["series_id"]),
        series_tag=str(result["series_tag"]),
        prompt_level=int(result["prompt_level"]),
        character_count=int(result["character_count"]),
        wildcard_path=str(result["wildcard_path"]),
        manifest_path=str(result["manifest_path"]),
        prompt_template=str(result["prompt_template"]),
        prompt_prefix=str(result.get("prompt_prefix") or ""),
        prompt_suffix=str(result.get("prompt_suffix") or ""),
        negative_prompt=str(result["negative_prompt"]),
        skipped=list(result.get("skipped") or []),
    )


@router.post("/series/{series_id}/start", response_model=GenerationJobState)
def start_generation_job(
    series_id: int,
    payload: GenerationStartRequest,
    db: Session = Depends(get_db),
):
    job = generation_job_manager.start_generation(
        series_id,
        character_ids=payload.character_ids,
        prompt_level=payload.prompt_level,
        require_confirmed=payload.require_confirmed,
    )
    return _job_to_schema(job)


@router.get("/jobs", response_model=GenerationJobListResponse)
def list_generation_jobs():
    return GenerationJobListResponse(
        items=[_job_to_schema(job) for job in generation_job_manager.list_visible_jobs()],
    )


@router.get("/jobs/{job_id}", response_model=GenerationJobState)
def get_generation_job(job_id: str):
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_schema(job)


@router.post("/jobs/{job_id}/cancel", response_model=GenerationJobState)
def cancel_generation_job(job_id: str):
    cancelled = generation_job_manager.cancel_job(job_id)
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not cancelled and job.status in {"queued", "running", "paused"}:
        raise HTTPException(status_code=409, detail="Job could not be cancelled")
    return _job_to_schema(job)


@router.post("/jobs/{job_id}/pause", response_model=GenerationJobState)
def pause_generation_job(job_id: str):
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=400, detail="Only running jobs can be paused")
    generation_job_manager.pause_job(job_id)
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_schema(job)


@router.post("/jobs/{job_id}/resume", response_model=GenerationJobState)
def resume_generation_job(job_id: str):
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    generation_job_manager.resume_job(job_id)
    job = generation_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_schema(job)


@router.get("/series/{series_id}/suggest-level", response_model=SuggestLevelResponse)
def suggest_prompt_level(
    series_id: int,
    character_ids: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    service = GenerationService(db)
    char_ids: list[int] | None = None
    if character_ids:
        try:
            char_ids = [int(x) for x in character_ids.split(",") if x.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="character_ids는 쉼표 구분 정수여야 합니다.") from exc
    result = service.suggest_batch_level(series_id=series_id, character_ids=char_ids)
    return SuggestLevelResponse(
        suggested_level=int(result["suggested_level"]),
        breakdown={int(k): v for k, v in result["breakdown"].items()},
    )
