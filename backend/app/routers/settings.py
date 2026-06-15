from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.collect_job_manager import series_job_manager
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def get_settings_service(db: Session = Depends(get_db)) -> SettingsService:
    return SettingsService(db)


@router.get("", response_model=SettingsResponse)
def get_settings(service: SettingsService = Depends(get_settings_service)):
    data = service.get_public_settings()
    return SettingsResponse(**data)


@router.patch("", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdateRequest,
    service: SettingsService = Depends(get_settings_service),
):
    if payload.danbooru_collect_max_concurrent is not None:
        service.set_collect_max_concurrent(payload.danbooru_collect_max_concurrent)
        series_job_manager.set_max_concurrent(payload.danbooru_collect_max_concurrent)
    if payload.naia_base_url is not None:
        service.set_naia_base_url(payload.naia_base_url)
    if payload.naia_portable_dir is not None:
        service.set_naia_portable_dir(payload.naia_portable_dir)
    if payload.generation_images_per_character is not None:
        service.set_generation_images_per_character(payload.generation_images_per_character)
    data = service.get_public_settings()
    return SettingsResponse(**data)
