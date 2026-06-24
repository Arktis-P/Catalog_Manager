from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    danbooru_collect_max_concurrent: int = Field(ge=1, le=5)
    danbooru_request_delay: float
    naia_base_url: str
    naia_portable_dir: str
    generation_images_per_character: int = Field(ge=1, le=4)
    generation_prompt_prefix: str
    generation_prompt_suffix: str
    generation_negative_prompt: str
    review_thumbnail_size: int = Field(ge=128, le=1024)
    review_max_loaded_images: int = Field(ge=10, le=120)
    min_character_post_count: int = Field(ge=0, le=500)
    hf_token: str = ""
    hf_wd_model: str = ""
    notification_mode: str = "each"
    notification_display: str = "toast"


class SettingsUpdateRequest(BaseModel):
    danbooru_collect_max_concurrent: int | None = Field(default=None, ge=1, le=5)
    naia_base_url: str | None = None
    naia_portable_dir: str | None = None
    generation_images_per_character: int | None = Field(default=None, ge=1, le=4)
    generation_prompt_prefix: str | None = None
    generation_prompt_suffix: str | None = None
    generation_negative_prompt: str | None = None
    review_thumbnail_size: int | None = Field(default=None, ge=128, le=1024)
    review_max_loaded_images: int | None = Field(default=None, ge=10, le=120)
    min_character_post_count: int | None = Field(default=None, ge=0, le=500)
    hf_token: str | None = None
    hf_wd_model: str | None = None
    notification_mode: str | None = None
    notification_display: str | None = None
