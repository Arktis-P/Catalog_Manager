from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.global_character import GlobalCharacter
from app.schemas.character_catalog import (
    CatalogCollectAllRequest,
    CatalogJobListResponse,
    CatalogJobResponse,
    CatalogListStartRequest,
    CatalogRetryFailedRequest,
    CatalogTagsStartRequest,
    GlobalCharacterListResponse,
    GlobalCharacterResponse,
)
from app.services.character_catalog_job_manager import character_catalog_job_manager
from app.services.character_catalog_service import CharacterCatalogService

router = APIRouter(prefix="/character-catalog", tags=["character-catalog"])


def get_catalog_service(db: Session = Depends(get_db)) -> CharacterCatalogService:
    return CharacterCatalogService(db)


def _require_danbooru() -> None:
    if not settings.danbooru_configured:
        raise HTTPException(status_code=400, detail="Configure Danbooru credentials in input/danbooru.env first.")


@router.get("/characters", response_model=GlobalCharacterListResponse)
def list_global_characters(
    search: str | None = None,
    gender: str | None = None,
    collect_status: str | None = None,
    series_id: int | None = Query(default=None, ge=1),
    min_post_count: int | None = Query(default=None, ge=0),
    max_post_count: int | None = Query(default=None, ge=0),
    has_image: bool | None = Query(default=None),
    has_cover: bool | None = Query(default=None),
    sort_by: str = Query(default="post_count"),
    sort_order: str = Query(default="desc"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    rows, total = service.list_characters(
        search=search,
        gender=gender,
        collect_status=collect_status,
        series_id=series_id,
        min_post_count=min_post_count,
        max_post_count=max_post_count,
        has_image=has_image,
        has_cover=has_cover,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return GlobalCharacterListResponse(
        items=[GlobalCharacterResponse.from_model(row) for row in rows],
        total=total,
    )


@router.get("/characters/{character_id}", response_model=GlobalCharacterResponse)
def get_global_character(character_id: int, service: CharacterCatalogService = Depends(get_catalog_service)):
    character = service.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return GlobalCharacterResponse.from_model(character)


@router.post("/list/start", response_model=CatalogJobResponse)
def start_catalog_list(payload: CatalogListStartRequest):
    _require_danbooru()
    job = character_catalog_job_manager.start_catalog_list(
        min_post_count=payload.min_post_count,
        restart=payload.restart,
    )
    return CatalogJobResponse.from_state(job)


@router.post("/tags/start", response_model=CatalogJobResponse)
def start_catalog_tags(payload: CatalogTagsStartRequest, db: Session = Depends(get_db)):
    _require_danbooru()
    unique_ids = list(dict.fromkeys(payload.character_ids))
    found = db.query(GlobalCharacter.id).filter(GlobalCharacter.id.in_(unique_ids)).count()
    if found != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more characters not found")
    job = character_catalog_job_manager.start_catalog_tags(unique_ids)
    return CatalogJobResponse.from_state(job)


@router.post("/tags/retry-failed", response_model=CatalogJobResponse)
def retry_failed_catalog_tags(
    payload: CatalogRetryFailedRequest,
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    _require_danbooru()
    ids = service.list_failed_ids(limit=payload.limit)
    if not ids:
        raise HTTPException(status_code=404, detail="No failed or partial characters to retry")
    job = character_catalog_job_manager.start_catalog_tags(ids)
    return CatalogJobResponse.from_state(job)


@router.post("/tags/collect-all", response_model=CatalogJobListResponse)
def collect_all_uncollected_catalog_tags(
    payload: CatalogCollectAllRequest,
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    """미수집(collect_status != completed) 캐릭터 전체를 post_count desc, id asc 순으로 모아
    chunk_size(기본 5000)개씩 나눠 각각 하나의 통합 태그 수집 job으로 작업 목록에 올린다."""
    _require_danbooru()
    ids = service.list_uncollected_ids(limit=payload.limit)
    if not ids:
        raise HTTPException(status_code=404, detail="No uncollected characters remaining")
    chunk_size = payload.chunk_size
    chunks = [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]
    jobs = [character_catalog_job_manager.start_catalog_tags(chunk) for chunk in chunks]
    return CatalogJobListResponse(items=[CatalogJobResponse.from_state(job) for job in jobs])


@router.get("/jobs", response_model=CatalogJobListResponse)
def list_catalog_jobs():
    jobs = character_catalog_job_manager.list_visible_jobs()
    return CatalogJobListResponse(items=[CatalogJobResponse.from_state(job) for job in jobs])


@router.get("/jobs/{job_id}", response_model=CatalogJobResponse)
def get_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/pause", response_model=CatalogJobResponse)
def pause_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=400, detail="Only running jobs can be paused")
    character_catalog_job_manager.pause_job(job_id)
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/resume", response_model=CatalogJobResponse)
def resume_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    character_catalog_job_manager.resume_job(job_id)
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/cancel", response_model=CatalogJobResponse)
def cancel_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "cancelled":
        return CatalogJobResponse.from_state(job)
    if job.status not in {"queued", "paused"}:
        raise HTTPException(status_code=400, detail="Only queued or paused jobs can be cancelled")
    if not character_catalog_job_manager.cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job could not be cancelled")
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)
