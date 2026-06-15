from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.danbooru.client import DanbooruAuthError, DanbooruClient
from app.models.character import Character
from app.models.series import Series
from app.schemas.character import CharacterListResponse, CharacterResponse, CharacterSeriesUpdate
from app.schemas.character_collect import (
    CharacterCollectRequest,
    CharacterCollectResultResponse,
    CharacterCollectSummaryResponse,
    CollectJobListResponse,
    CollectJobResponse,
)
from app.services.character_service import CharacterService
from app.services.collect_job_manager import series_job_manager

router = APIRouter(prefix="/characters", tags=["characters"])


def get_character_service(db: Session = Depends(get_db)) -> CharacterService:
    return CharacterService(db)


def _character_response(character, series) -> CharacterResponse:
    return CharacterResponse(
        id=character.id,
        series_id=character.series_id,
        series_tag=series.series_tag,
        series_display_name=series.display_name,
        character_tag=character.character_tag,
        display_name=character.display_name,
        danbooru_url=character.danbooru_url,
        post_count=character.post_count,
        multi_color_hair=character.multi_color_hair,
        hair_color=character.hair_color,
        hair_shape=character.hair_shape,
        eye_color=character.eye_color,
        feature_tags=character.feature_tags,
        gender=normalize_gender(character.gender),
        generation_prompt=character.generation_prompt,
        appearance_confirmed=character.appearance_confirmed,
        status=character.status,
        from_wiki=character.from_wiki,
        from_list_page=character.from_list_page,
        from_posts=character.from_posts,
        from_related=character.from_related,
        needs_check_reason=character.needs_check_reason,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


@router.get("/danbooru/status")
def danbooru_status():
    if not settings.danbooru_configured:
        return {
            "configured": False,
            "ready": False,
            "message": "Configure input/danbooru.env first.",
        }
    try:
        client = DanbooruClient()
        verification = client.verify_credentials()
        return {
            "configured": True,
            "ready": True,
            "message": "pybooru client ready",
            **verification,
        }
    except DanbooruAuthError as exc:
        return {
            "configured": True,
            "ready": False,
            "message": str(exc),
        }
    except Exception as exc:
        return {
            "configured": True,
            "ready": False,
            "message": str(exc),
        }


@router.post("/collect", response_model=CharacterCollectSummaryResponse | CharacterCollectResultResponse)
def collect_characters(
    payload: CharacterCollectRequest,
    service: CharacterService = Depends(get_character_service),
):
    try:
        if payload.series_id is not None:
            series = service.db.query(Series).filter(Series.id == payload.series_id).first()
            if not series:
                raise HTTPException(status_code=404, detail="Series not found")
            result = service.collect_for_series(series)
            return CharacterCollectResultResponse(**result.__dict__)

        if payload.series_tag:
            result = service.collect_for_series_tag(payload.series_tag)
            return CharacterCollectResultResponse(**result.__dict__)

        summary = service.collect_batch(status=payload.status, limit=payload.limit)
        return CharacterCollectSummaryResponse(
            series_processed=summary.series_processed,
            total_discovered=summary.total_discovered,
            total_created=summary.total_created,
            total_skipped_existing=summary.total_skipped_existing,
            results=[CharacterCollectResultResponse(**item.__dict__) for item in summary.results],
        )
    except DanbooruAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/series/{series_id}/collect/start", response_model=CollectJobResponse)
def start_collect_characters_for_series(series_id: int, db: Session = Depends(get_db)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if not settings.danbooru_configured:
        raise HTTPException(status_code=400, detail="Configure Danbooru credentials in input/danbooru.env first.")
    job = series_job_manager.start_series_collect(series_id)
    return CollectJobResponse.from_state(job)


@router.post("/series/{series_id}/appearance/start", response_model=CollectJobResponse)
def start_appearance_extract_for_series(series_id: int, db: Session = Depends(get_db)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if not settings.danbooru_configured:
        raise HTTPException(status_code=400, detail="Configure Danbooru credentials in input/danbooru.env first.")
    character_count = db.query(Character).filter(Character.series_id == series_id).count()
    if character_count <= 0:
        raise HTTPException(
            status_code=400,
            detail="Collect characters for this series before extracting appearance tags.",
        )
    job = series_job_manager.start_appearance_extract(series_id)
    return CollectJobResponse.from_state(job)


@router.get("/collect/jobs", response_model=CollectJobListResponse)
def list_collect_jobs():
    jobs = series_job_manager.list_visible_jobs()
    return CollectJobListResponse(items=[CollectJobResponse.from_state(job) for job in jobs])


@router.get("/collect/jobs/{job_id}", response_model=CollectJobResponse)
def get_collect_job(job_id: str):
    job = series_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Collect job not found")
    return CollectJobResponse.from_state(job)


@router.get("/series/{series_id}/collect/active", response_model=CollectJobResponse)
def get_active_collect_job_for_series(series_id: int):
    job = series_job_manager.get_active_job_for_series(series_id)
    if not job:
        raise HTTPException(status_code=404, detail="No active collect job for this series")
    return CollectJobResponse.from_state(job)


@router.post("/series/{series_id}/collect", response_model=CharacterCollectResultResponse)
def collect_characters_for_series(
    series_id: int,
    service: CharacterService = Depends(get_character_service),
):
    series = service.db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    try:
        result = service.collect_for_series(series)
        return CharacterCollectResultResponse(**result.__dict__)
    except DanbooruAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/export/csv")
def export_characters_csv(
    series_id: int | None = Query(default=None, ge=1),
    search: str | None = None,
    service: CharacterService = Depends(get_character_service),
):
    if series_id is not None:
        series = service.db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
    content = service.export_csv(series_id=series_id, search=search)
    filename = "characters.csv" if series_id is None else f"characters-{series_id}.csv"
    return PlainTextResponse(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/series/{series_id}/characters", response_model=CharacterListResponse)
def list_characters_for_series(
    series_id: int,
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    service: CharacterService = Depends(get_character_service),
):
    series = service.db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    rows, total = service.list_characters(series_id=series_id, search=search, skip=skip, limit=limit)
    return CharacterListResponse(
        items=[_character_response(character, row_series) for character, row_series in rows],
        total=total,
    )


@router.patch("/{character_id}/series", response_model=CharacterResponse)
def update_character_series(
    character_id: int,
    payload: CharacterSeriesUpdate,
    service: CharacterService = Depends(get_character_service),
):
    try:
        character = service.update_character_series(character_id, payload.series_id)
        series = service.db.query(Series).filter(Series.id == character.series_id).first()
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
        return _character_response(character, series)
    except DanbooruAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
