from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.series import SERIES_STATUSES, SeriesCreate, SeriesListResponse, SeriesResponse, SeriesUpdate
from app.services.series_service import SeriesService

router = APIRouter(prefix="/series", tags=["series"])


def get_series_service(db: Session = Depends(get_db)) -> SeriesService:
    return SeriesService(db)


@router.get("/statuses")
def list_statuses() -> list[str]:
    return SERIES_STATUSES


@router.get("", response_model=SeriesListResponse)
def list_series(
    status: str | None = None,
    search: str | None = None,
    sort_by: str = Query(default="post_count"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: SeriesService = Depends(get_series_service),
):
    items, total = service.list_series(
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return SeriesListResponse(items=items, total=total)


@router.get("/export/csv")
def export_series_csv(service: SeriesService = Depends(get_series_service)):
    content = service.export_csv()
    return PlainTextResponse(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="series.csv"'},
    )


@router.post("/import/csv")
async def import_series_csv(
    file: UploadFile = File(...),
    replace: bool = Query(default=False),
    service: SeriesService = Depends(get_series_service),
):
    content = (await file.read()).decode("utf-8-sig")
    try:
        result = service.import_csv(content, replace=replace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/{series_id}", response_model=SeriesResponse)
def get_series(series_id: int, service: SeriesService = Depends(get_series_service)):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


@router.post("", response_model=SeriesResponse, status_code=201)
def create_series(data: SeriesCreate, service: SeriesService = Depends(get_series_service)):
    if service.get_by_tag(data.series_tag):
        raise HTTPException(status_code=409, detail="Series tag already exists")
    return service.create_series(data)


@router.patch("/{series_id}", response_model=SeriesResponse)
def update_series(
    series_id: int,
    data: SeriesUpdate,
    service: SeriesService = Depends(get_series_service),
):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if data.series_tag and data.series_tag != series.series_tag:
        if service.get_by_tag(data.series_tag):
            raise HTTPException(status_code=409, detail="Series tag already exists")
    return service.update_series(series, data)


@router.delete("/{series_id}", status_code=204)
def delete_series(series_id: int, service: SeriesService = Depends(get_series_service)):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    service.delete_series(series)
