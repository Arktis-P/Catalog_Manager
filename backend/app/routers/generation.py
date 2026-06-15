from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.generation import (
    GenerationCandidate,
    GenerationCandidateListResponse,
    GenerationJobListResponse,
    GenerationJobState,
    GenerationPreviewResponse,
    GenerationQueuePreviewResponse,
    GenerationStartRequest,
    NaiaStatusResponse,
)
from app.services.generation_job_manager import generation_job_manager
from app.services.generation_service import GenerationService

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
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/naia/status", response_model=NaiaStatusResponse)
def get_naia_status(db: Session = Depends(get_db)):
    return GenerationService(db).naia_status()


@router.get("/series/{series_id}/candidates", response_model=GenerationCandidateListResponse)
def list_generation_candidates(
    series_id: int,
    require_confirmed: bool = Query(default=True),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    service = GenerationService(db)
    items = service.list_generation_candidates(
        series_id,
        require_confirmed=require_confirmed,
        search=search,
    )
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
            )
            for character in items
        ],
        total=len(items),
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
    if not cancelled and job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Job could not be cancelled")
    return _job_to_schema(job)
