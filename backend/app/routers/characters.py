from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.danbooru.client import DanbooruAuthError
from app.models.series import Series
from app.schemas.character_collect import (
    CharacterCollectRequest,
    CharacterCollectResultResponse,
    CharacterCollectSummaryResponse,
)
from app.services.character_service import CharacterService

router = APIRouter(prefix="/characters", tags=["characters"])


def get_character_service(db: Session = Depends(get_db)) -> CharacterService:
    return CharacterService(db)


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
