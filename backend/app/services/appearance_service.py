from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.danbooru.appearance_extractor import AppearanceExtractor
from app.models.character import Character
from app.models.series import Series
from app.services.prompt_service import build_generation_prompt

AppearanceProgressCallback = Callable[[dict[str, object]], None]


@dataclass
class AppearanceExtractResult:
    series_tag: str
    processed: int
    updated: int


class AppearanceService:
    def __init__(self, db: Session, extractor: AppearanceExtractor | None = None):
        self.db = db
        self.extractor = extractor or AppearanceExtractor()

    def extract_for_series(
        self,
        series: Series,
        *,
        progress_callback: AppearanceProgressCallback | None = None,
    ) -> AppearanceExtractResult:
        characters = (
            self.db.query(Character)
            .filter(Character.series_id == series.id)
            .order_by(Character.character_tag.asc())
            .all()
        )
        total = len(characters)
        updated = 0

        if progress_callback:
            progress_callback(
                {
                    "phase": "starting",
                    "message": f"{series.series_tag} 외형 태그 추출 시작 · {total}명",
                    "current": 0,
                    "total": total,
                }
            )

        for index, character in enumerate(characters, start=1):
            appearance = self.extractor.extract_for_character(character.character_tag)
            character.multi_color_hair = appearance.multi_color_hair
            character.hair_color = appearance.hair_color
            character.hair_shape = appearance.hair_shape
            character.eye_color = appearance.eye_color
            character.feature_tags = appearance.feature_tags
            character.from_related = True
            character.appearance_confirmed = False
            character.generation_prompt = build_generation_prompt(character)
            updated += 1

            if progress_callback:
                progress_callback(
                    {
                        "phase": "extracting",
                        "message": f"외형 태그 추출 {index}/{total} · {character.character_tag}",
                        "current": index,
                        "total": total,
                    }
                )

        self.db.commit()
        return AppearanceExtractResult(
            series_tag=series.series_tag,
            processed=total,
            updated=updated,
        )
