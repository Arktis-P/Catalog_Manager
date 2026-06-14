from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    danbooru_collect_max_concurrent: int = Field(ge=1, le=5)
    danbooru_request_delay: float


class SettingsUpdateRequest(BaseModel):
    danbooru_collect_max_concurrent: int = Field(ge=1, le=5)
