from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.character import (
    CATALOG_STATUSES,
    CatalogItemResponse,
    CatalogItemUpdateRequest,
    CatalogListResponse,
    GlobalCatalogListResponse,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


def get_catalog_service(db: Session = Depends(get_db)) -> CatalogService:
    return CatalogService(db)


def _catalog_filter_kwargs(
    *,
    series_tag: str | None = None,
    rating: int | None = None,
    gender: str | None = None,
    type: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    feature_tags: str | None = None,
    status: str | None = None,
    has_cover_image: bool | None = None,
    needs_review: bool | None = None,
    needs_regen: bool | None = None,
    search: str | None = None,
):
    return {
        "series_tag": series_tag,
        "rating": rating,
        "gender": gender,
        "type_": type,
        "hair_color": hair_color,
        "eye_color": eye_color,
        "feature_tags": feature_tags,
        "status": status,
        "has_cover_image": has_cover_image,
        "needs_review": needs_review,
        "needs_regen": needs_regen,
        "search": search,
    }


@router.get("/statuses")
def list_catalog_statuses() -> list[str]:
    return CATALOG_STATUSES


@router.get("/stats")
def get_catalog_stats(service: CatalogService = Depends(get_catalog_service)):
    return service.get_stats()


@router.get("/random", response_model=CatalogItemResponse)
def get_random_catalog_character(
    series_tag: str | None = None,
    rating: int | None = Query(default=None, ge=-1, le=6),
    gender: str | None = None,
    type: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    feature_tags: str | None = None,
    status: str | None = None,
    has_cover_image: bool | None = True,
    needs_review: bool | None = None,
    needs_regen: bool | None = None,
    search: str | None = None,
    include_hidden_ratings: bool = False,
    service: CatalogService = Depends(get_catalog_service),
):
    item = service.get_random_character(
        **_catalog_filter_kwargs(
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type=type,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
        ),
        include_hidden_ratings=include_hidden_ratings,
    )
    if not item:
        raise HTTPException(status_code=404, detail="No matching character found")
    return item


@router.get("/export/csv")
def export_catalog_csv(
    series_tag: str | None = None,
    rating: int | None = Query(default=None, ge=-1, le=6),
    gender: str | None = None,
    type: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    feature_tags: str | None = None,
    status: str | None = None,
    has_cover_image: bool | None = None,
    needs_review: bool | None = None,
    needs_regen: bool | None = None,
    search: str | None = None,
    include_hidden_ratings: bool = False,
    service: CatalogService = Depends(get_catalog_service),
):
    content, saved_path = service.export_catalog_csv(
        **_catalog_filter_kwargs(
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type=type,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
        ),
        include_hidden_ratings=include_hidden_ratings,
    )
    headers = {"Content-Disposition": 'attachment; filename="catalog-export.csv"'}
    if saved_path:
        headers["X-Export-Path"] = saved_path
    return PlainTextResponse(content=content, media_type="text/csv; charset=utf-8", headers=headers)


@router.get("", response_model=CatalogListResponse)
def list_catalog(
    series_tag: str | None = None,
    rating: int | None = Query(default=None, ge=-1, le=6),
    gender: str | None = None,
    type: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    feature_tags: str | None = None,
    status: str | None = None,
    has_cover_image: bool | None = None,
    needs_review: bool | None = None,
    needs_regen: bool | None = None,
    search: str | None = None,
    include_hidden_ratings: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CatalogService = Depends(get_catalog_service),
):
    items, total = service.list_catalog(
        **_catalog_filter_kwargs(
            series_tag=series_tag,
            rating=rating,
            gender=gender,
            type=type,
            hair_color=hair_color,
            eye_color=eye_color,
            feature_tags=feature_tags,
            status=status,
            has_cover_image=has_cover_image,
            needs_review=needs_review,
            needs_regen=needs_regen,
            search=search,
        ),
        include_hidden_ratings=include_hidden_ratings,
        skip=skip,
        limit=limit,
    )
    return CatalogListResponse(items=items, total=total)


@router.get("/global", response_model=GlobalCatalogListResponse)
def list_global_catalog(
    rating: int | None = Query(default=None, ge=-1, le=6),
    gender: str | None = None,
    search: str | None = None,
    include_hidden_ratings: bool = False,
    has_alternative: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CatalogService = Depends(get_catalog_service),
):
    items, total = service.list_global_catalog(
        rating=rating,
        gender=gender,
        search=search,
        include_hidden_ratings=include_hidden_ratings,
        has_alternative=has_alternative,
        skip=skip,
        limit=limit,
    )
    return GlobalCatalogListResponse(items=items, total=total)


@router.patch("/{character_id}", response_model=CatalogItemResponse)
def update_catalog_item(
    character_id: int,
    payload: CatalogItemUpdateRequest,
    service: CatalogService = Depends(get_catalog_service),
):
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        if "type" in update_data:
            update_data["type_"] = update_data.pop("type")
        return service.update_catalog_item(character_id, **update_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
