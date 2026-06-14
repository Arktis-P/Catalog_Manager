from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models.setting import Setting

SETTING_COLLECT_MAX_CONCURRENT = "danbooru_collect_max_concurrent"
MIN_COLLECT_MAX_CONCURRENT = 1
MAX_COLLECT_MAX_CONCURRENT = 5


class SettingsService:
    def __init__(self, db: Session):
        self.db = db

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

    def get_public_settings(self) -> dict[str, int | float]:
        return {
            "danbooru_collect_max_concurrent": self.get_collect_max_concurrent(),
            "danbooru_request_delay": settings.danbooru_request_delay,
        }
