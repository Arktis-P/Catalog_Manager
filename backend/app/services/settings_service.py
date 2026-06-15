from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models.setting import Setting

SETTING_COLLECT_MAX_CONCURRENT = "danbooru_collect_max_concurrent"
SETTING_NAIA_BASE_URL = "naia_base_url"
SETTING_NAIA_PORTABLE_DIR = "naia_portable_dir"
SETTING_GENERATION_IMAGES_PER_CHARACTER = "generation_images_per_character"
DEFAULT_NAIA_BASE_URL = "http://127.0.0.1:7243"
MIN_COLLECT_MAX_CONCURRENT = 1
MAX_COLLECT_MAX_CONCURRENT = 5
MIN_IMAGES_PER_CHARACTER = 1
MAX_IMAGES_PER_CHARACTER = 4


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
        self.db.commit()

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
        self.db.commit()
        return clamped

    def get_naia_base_url(self) -> str:
        from app.services.generation_service import DEFAULT_NAIA_BASE_URL

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
            return 1
        try:
            return max(MIN_IMAGES_PER_CHARACTER, min(MAX_IMAGES_PER_CHARACTER, int(raw)))
        except ValueError:
            return 1

    def set_generation_images_per_character(self, value: int) -> int:
        clamped = max(MIN_IMAGES_PER_CHARACTER, min(MAX_IMAGES_PER_CHARACTER, value))
        self._set_setting(SETTING_GENERATION_IMAGES_PER_CHARACTER, str(clamped))
        return clamped

    def get_public_settings(self) -> dict[str, int | float | str]:
        return {
            "danbooru_collect_max_concurrent": self.get_collect_max_concurrent(),
            "danbooru_request_delay": settings.danbooru_request_delay,
            "naia_base_url": self.get_naia_base_url(),
            "naia_portable_dir": self.get_naia_portable_dir(),
            "generation_images_per_character": self.get_generation_images_per_character(),
        }
