from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models.setting import Setting
from app.services.db_write_queue import commit_db_session
from app.services.generation_prompt_builder import (
    GenerationPromptConfig,
    default_generation_prompt_config,
)

SETTING_COLLECT_MAX_CONCURRENT = "danbooru_collect_max_concurrent"
SETTING_NAIA_BASE_URL = "naia_base_url"
SETTING_NAIA_PORTABLE_DIR = "naia_portable_dir"
SETTING_GENERATION_IMAGES_PER_CHARACTER = "generation_images_per_character"
SETTING_GENERATION_PROMPT_PREFIX = "generation_prompt_prefix"
SETTING_GENERATION_PROMPT_SUFFIX = "generation_prompt_suffix"
SETTING_GENERATION_NEGATIVE_PROMPT = "generation_negative_prompt"
SETTING_REVIEW_THUMBNAIL_SIZE = "review_thumbnail_size"
SETTING_REVIEW_MAX_LOADED_IMAGES = "review_max_loaded_images"
SETTING_MIN_CHARACTER_POST_COUNT = "min_character_post_count"
SETTING_HF_TOKEN = "hf_token"
SETTING_HF_WD_MODEL = "hf_wd_model"
DEFAULT_NAIA_BASE_URL = "http://127.0.0.1:7243"
DEFAULT_IMAGES_PER_CHARACTER = 2
DEFAULT_REVIEW_THUMBNAIL_SIZE = 384
DEFAULT_REVIEW_MAX_LOADED_IMAGES = 30
DEFAULT_MIN_CHARACTER_POST_COUNT = 10
MIN_COLLECT_MAX_CONCURRENT = 1
MAX_COLLECT_MAX_CONCURRENT = 5
MIN_IMAGES_PER_CHARACTER = 1
MAX_IMAGES_PER_CHARACTER = 4
MIN_REVIEW_THUMBNAIL_SIZE = 128
MAX_REVIEW_THUMBNAIL_SIZE = 1024
MIN_REVIEW_MAX_LOADED_IMAGES = 10
MAX_REVIEW_MAX_LOADED_IMAGES = 120
MIN_CHARACTER_POST_COUNT = 0
MAX_CHARACTER_POST_COUNT = 500


class SettingsService:
    def __init__(self, db: Session):
        self.db = db

    def _get_setting(self, key: str) -> str | None:
        row = self.db.query(Setting).filter(Setting.key == key).first()
        if not row or not row.value:
            return None
        return row.value.strip()

    def _set_setting(self, key: str, value: str) -> None:
        row = self.db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
        else:
            self.db.add(Setting(key=key, value=value))
        commit_db_session(self.db)

    def get_collect_max_concurrent(self) -> int:
        row = self.db.query(Setting).filter(Setting.key == SETTING_COLLECT_MAX_CONCURRENT).first()
        if not row or not row.value:
            return settings.danbooru_collect_max_concurrent
        try:
            value = int(row.value)
        except ValueError:
            return settings.danbooru_collect_max_concurrent
        return max(MIN_COLLECT_MAX_CONCURRENT, min(MAX_COLLECT_MAX_CONCURRENT, value))

    def set_collect_max_concurrent(self, value: int) -> int:
        clamped = max(MIN_COLLECT_MAX_CONCURRENT, min(MAX_COLLECT_MAX_CONCURRENT, value))
        row = self.db.query(Setting).filter(Setting.key == SETTING_COLLECT_MAX_CONCURRENT).first()
        if row:
            row.value = str(clamped)
        else:
            self.db.add(Setting(key=SETTING_COLLECT_MAX_CONCURRENT, value=str(clamped)))
        commit_db_session(self.db)
        return clamped

    def get_naia_base_url(self) -> str:
        return self._get_setting(SETTING_NAIA_BASE_URL) or DEFAULT_NAIA_BASE_URL

    def set_naia_base_url(self, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        self._set_setting(SETTING_NAIA_BASE_URL, cleaned)
        return cleaned

    def get_naia_portable_dir(self) -> str:
        default = str(settings.project_root.parent / "NAIA_Portable")
        return self._get_setting(SETTING_NAIA_PORTABLE_DIR) or default

    def set_naia_portable_dir(self, value: str) -> str:
        cleaned = value.strip()
        self._set_setting(SETTING_NAIA_PORTABLE_DIR, cleaned)
        return cleaned

    def get_generation_images_per_character(self) -> int:
        raw = self._get_setting(SETTING_GENERATION_IMAGES_PER_CHARACTER)
        if not raw:
            return DEFAULT_IMAGES_PER_CHARACTER
        try:
            return max(MIN_IMAGES_PER_CHARACTER, min(MAX_IMAGES_PER_CHARACTER, int(raw)))
        except ValueError:
            return DEFAULT_IMAGES_PER_CHARACTER

    def set_generation_images_per_character(self, value: int) -> int:
        clamped = max(MIN_IMAGES_PER_CHARACTER, min(MAX_IMAGES_PER_CHARACTER, value))
        self._set_setting(SETTING_GENERATION_IMAGES_PER_CHARACTER, str(clamped))
        return clamped

    def get_review_thumbnail_size(self) -> int:
        raw = self._get_setting(SETTING_REVIEW_THUMBNAIL_SIZE)
        if not raw:
            return DEFAULT_REVIEW_THUMBNAIL_SIZE
        try:
            return max(MIN_REVIEW_THUMBNAIL_SIZE, min(MAX_REVIEW_THUMBNAIL_SIZE, int(raw)))
        except ValueError:
            return DEFAULT_REVIEW_THUMBNAIL_SIZE

    def set_review_thumbnail_size(self, value: int) -> int:
        clamped = max(MIN_REVIEW_THUMBNAIL_SIZE, min(MAX_REVIEW_THUMBNAIL_SIZE, value))
        self._set_setting(SETTING_REVIEW_THUMBNAIL_SIZE, str(clamped))
        return clamped

    def get_review_max_loaded_images(self) -> int:
        raw = self._get_setting(SETTING_REVIEW_MAX_LOADED_IMAGES)
        if not raw:
            return DEFAULT_REVIEW_MAX_LOADED_IMAGES
        try:
            return max(MIN_REVIEW_MAX_LOADED_IMAGES, min(MAX_REVIEW_MAX_LOADED_IMAGES, int(raw)))
        except ValueError:
            return DEFAULT_REVIEW_MAX_LOADED_IMAGES

    def set_review_max_loaded_images(self, value: int) -> int:
        clamped = max(MIN_REVIEW_MAX_LOADED_IMAGES, min(MAX_REVIEW_MAX_LOADED_IMAGES, value))
        self._set_setting(SETTING_REVIEW_MAX_LOADED_IMAGES, str(clamped))
        return clamped

    def get_hf_token(self) -> str:
        return self._get_setting(SETTING_HF_TOKEN) or ""

    def set_hf_token(self, value: str) -> str:
        cleaned = value.strip()
        self._set_setting(SETTING_HF_TOKEN, cleaned)
        return cleaned

    def get_hf_wd_model(self) -> str:
        from app.integrations.image_tagger.hf_wd_tagger import DEFAULT_HF_WD_MODEL
        return self._get_setting(SETTING_HF_WD_MODEL) or DEFAULT_HF_WD_MODEL

    def set_hf_wd_model(self, value: str) -> str:
        cleaned = value.strip()
        self._set_setting(SETTING_HF_WD_MODEL, cleaned)
        return cleaned

    def get_min_character_post_count(self) -> int:
        raw = self._get_setting(SETTING_MIN_CHARACTER_POST_COUNT)
        if not raw:
            return DEFAULT_MIN_CHARACTER_POST_COUNT
        try:
            return max(MIN_CHARACTER_POST_COUNT, min(MAX_CHARACTER_POST_COUNT, int(raw)))
        except ValueError:
            return DEFAULT_MIN_CHARACTER_POST_COUNT

    def set_min_character_post_count(self, value: int) -> int:
        clamped = max(MIN_CHARACTER_POST_COUNT, min(MAX_CHARACTER_POST_COUNT, value))
        self._set_setting(SETTING_MIN_CHARACTER_POST_COUNT, str(clamped))
        return clamped

    def get_generation_prompt_config(self) -> GenerationPromptConfig:
        defaults = default_generation_prompt_config()
        return GenerationPromptConfig(
            prefix=self._get_setting(SETTING_GENERATION_PROMPT_PREFIX) or defaults.prefix,
            suffix=self._get_setting(SETTING_GENERATION_PROMPT_SUFFIX) or defaults.suffix,
            negative_prompt=self._get_setting(SETTING_GENERATION_NEGATIVE_PROMPT) or defaults.negative_prompt,
        )

    def set_generation_prompt_config(
        self,
        *,
        prefix: str | None = None,
        suffix: str | None = None,
        negative_prompt: str | None = None,
    ) -> GenerationPromptConfig:
        if prefix is not None:
            self._set_setting(SETTING_GENERATION_PROMPT_PREFIX, prefix)
        if suffix is not None:
            self._set_setting(SETTING_GENERATION_PROMPT_SUFFIX, suffix)
        if negative_prompt is not None:
            self._set_setting(SETTING_GENERATION_NEGATIVE_PROMPT, negative_prompt)
        return self.get_generation_prompt_config()

    def get_public_settings(self) -> dict[str, int | float | str]:
        prompt_config = self.get_generation_prompt_config()
        return {
            "danbooru_collect_max_concurrent": self.get_collect_max_concurrent(),
            "danbooru_request_delay": settings.danbooru_request_delay,
            "naia_base_url": self.get_naia_base_url(),
            "naia_portable_dir": self.get_naia_portable_dir(),
            "generation_images_per_character": self.get_generation_images_per_character(),
            "generation_prompt_prefix": prompt_config.prefix,
            "generation_prompt_suffix": prompt_config.suffix,
            "generation_negative_prompt": prompt_config.negative_prompt,
            "review_thumbnail_size": self.get_review_thumbnail_size(),
            "review_max_loaded_images": self.get_review_max_loaded_images(),
            "min_character_post_count": self.get_min_character_post_count(),
            "hf_token": self.get_hf_token(),
            "hf_wd_model": self.get_hf_wd_model(),
        }
