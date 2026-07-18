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
    if (
        payload.generation_prompt_prefix is not None
        or payload.generation_prompt_suffix is not None
        or payload.generation_negative_prompt is not None
    ):
        service.set_generation_prompt_config(
            prefix=payload.generation_prompt_prefix,
            suffix=payload.generation_prompt_suffix,
            negative_prompt=payload.generation_negative_prompt,
        )
    if payload.review_thumbnail_size is not None:
        service.set_review_thumbnail_size(payload.review_thumbnail_size)
    if payload.review_max_loaded_images is not None:
        service.set_review_max_loaded_images(payload.review_max_loaded_images)
    if payload.min_character_post_count is not None:
        service.set_min_character_post_count(payload.min_character_post_count)
    if payload.hf_token is not None:
        service.set_hf_token(payload.hf_token)
    if payload.hf_wd_model is not None:
        service.set_hf_wd_model(payload.hf_wd_model)
    if payload.notification_mode is not None:
        service.set_notification_mode(payload.notification_mode)
    if payload.notification_display is not None:
        service.set_notification_display(payload.notification_display)
    if payload.v2_review_card_size is not None:
        service.set_v2_review_card_size(payload.v2_review_card_size)
    if payload.v2_review_card_width_px is not None:
        service.set_v2_review_card_width_px(payload.v2_review_card_width_px)
    data = service.get_public_settings()
    return SettingsResponse(**data)
