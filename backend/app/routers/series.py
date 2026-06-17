from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.series import (
    SERIES_STATUSES,
    SeriesCreate,
    SeriesListResponse,
    SeriesMergeCandidate,
    SeriesMergeCandidateListResponse,
    SeriesMergePreviewResponse,
    SeriesMergeRequest,
    SeriesMergeResponse,
    SeriesResponse,
    SeriesUnmergeResponse,
    SeriesUpdate,
)
from app.services.series_merge_service import SeriesMergeService, similarity_score
from app.services.series_service import SeriesService

router = APIRouter(prefix="/series", tags=["series"])


def get_series_service(db: Session = Depends(get_db)) -> SeriesService:
    return SeriesService(db)


@router.get("/statuses")
def list_statuses() -> list[str]:
    return SERIES_STATUSES


def get_merge_service(db: Session = Depends(get_db)) -> SeriesMergeService:
    return SeriesMergeService(db)


@router.get("", response_model=SeriesListResponse)
def list_series(
    status: str | None = None,
    search: str | None = None,
    sort_by: str = Query(default="post_count"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    hierarchical: bool = Query(default=True),
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
    responses = service.to_response_list(items)
    if hierarchical:
        responses = service.flatten_hierarchical(responses)
    return SeriesListResponse(items=responses, total=total)


@router.get("/{series_id}/merge/candidates", response_model=SeriesMergeCandidateListResponse)
def list_merge_candidates(
    series_id: int,
    mode: str = Query(default="parent", pattern="^(parent|child)$"),
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    exclude_ids: str | None = Query(
        default=None,
        description="Comma-separated series IDs to exclude from candidates",
    ),
    service: SeriesService = Depends(get_series_service),
    merge_service: SeriesMergeService = Depends(get_merge_service),
):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    excluded: set[int] = set()
    if exclude_ids:
        for part in exclude_ids.split(","):
            part = part.strip()
            if part.isdigit():
                excluded.add(int(part))

    if mode == "parent":
        candidates = merge_service.list_parent_candidates(
            series,
            search=search,
            limit=limit,
            exclude_ids=excluded or None,
        )
        anchor = series
    else:
        candidates = merge_service.list_child_candidates(
            series,
            search=search,
            limit=limit,
            exclude_ids=excluded or None,
        )
        anchor = series

    counts = service.get_character_counts([item.id for item in candidates])
    return SeriesMergeCandidateListResponse(
        items=[
            SeriesMergeCandidate(
                id=item.id,
                series_tag=item.series_tag,
                display_name=item.display_name,
                status=item.status,
                post_count=item.post_count,
                character_count=counts.get(item.id, 0),
                similarity_score=similarity_score(anchor, item),
                mergeable=merge_service.candidate_is_mergeable(item),
            )
            for item in candidates
        ]
    )


@router.get("/{series_id}/merge/preview", response_model=SeriesMergePreviewResponse)
def preview_series_merge(
    series_id: int,
    parent_series_id: int = Query(ge=1),
    merge_service: SeriesMergeService = Depends(get_merge_service),
):
    try:
        preview = merge_service.preview_merge(series_id, parent_series_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SeriesMergePreviewResponse(**preview.__dict__)


@router.post("/{series_id}/merge", response_model=SeriesMergeResponse)
def merge_series(
    series_id: int,
    payload: SeriesMergeRequest,
    merge_service: SeriesMergeService = Depends(get_merge_service),
):
    try:
        result = merge_service.merge_into_parent(series_id, payload.parent_series_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SeriesMergeResponse(**result.__dict__)


@router.delete("/{series_id}/merge", response_model=SeriesUnmergeResponse)
def unmerge_series(series_id: int, merge_service: SeriesMergeService = Depends(get_merge_service)):
    try:
        result = merge_service.unmerge(series_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SeriesUnmergeResponse(**result.__dict__)


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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc
    return result


@router.get("/{series_id}", response_model=SeriesResponse)
def get_series(series_id: int, service: SeriesService = Depends(get_series_service)):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    counts = service.get_character_counts([series.id])
    appearance_counts = service.get_appearance_extracted_counts([series.id])
    return service.to_response(
        series,
        character_count=counts.get(series.id, 0),
        appearance_extracted_count=appearance_counts.get(series.id, 0),
    )


@router.post("", response_model=SeriesResponse, status_code=201)
def create_series(data: SeriesCreate, service: SeriesService = Depends(get_series_service)):
    if service.get_by_tag(data.series_tag):
        raise HTTPException(status_code=409, detail="Series tag already exists")
    series = service.create_series(data)
    return service.to_response(series, character_count=0)


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
    updated = service.update_series(series, data)
    counts = service.get_character_counts([updated.id])
    appearance_counts = service.get_appearance_extracted_counts([updated.id])
    return service.to_response(
        updated,
        character_count=counts.get(updated.id, 0),
        appearance_extracted_count=appearance_counts.get(updated.id, 0),
    )


@router.delete("/{series_id}", status_code=204)
def delete_series(series_id: int, service: SeriesService = Depends(get_series_service)):
    series = service.get_series(series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    try:
        service.delete_series(series)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
