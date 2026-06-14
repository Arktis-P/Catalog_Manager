from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.character import CATALOG_STATUSES, CatalogListResponse
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


def get_catalog_service(db: Session = Depends(get_db)) -> CatalogService:
    return CatalogService(db)


@router.get("/statuses")
def list_catalog_statuses() -> list[str]:
    return CATALOG_STATUSES


@router.get("/stats")
def get_catalog_stats(service: CatalogService = Depends(get_catalog_service)):
    return service.get_stats()


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
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: CatalogService = Depends(get_catalog_service),
):
    items, total = service.list_catalog(
        series_tag=series_tag,
        rating=rating,
        gender=gender,
        type_=type,
        hair_color=hair_color,
        eye_color=eye_color,
        feature_tags=feature_tags,
        status=status,
        has_cover_image=has_cover_image,
        needs_review=needs_review,
        needs_regen=needs_regen,
        search=search,
        skip=skip,
        limit=limit,
    )
    return CatalogListResponse(items=items, total=total)
