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
