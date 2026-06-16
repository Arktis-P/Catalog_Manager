from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.danbooru.appearance_extractor import (
    AppearanceExtractor,
    extract_appearance_tags,
    normalize_gender,
    parse_related_tags,
)
from app.integrations.danbooru.series_membership import (
    MEMBERSHIP_MISMATCH_PREFIX,
    evaluate_series_membership,
    fetch_copyright_related_tags,
)
from app.models.character import Character
from app.models.series import Series
from app.services.prompt_service import build_generation_prompt

AppearanceProgressCallback = Callable[[dict[str, object]], None]


@dataclass
class AppearanceExtractResult:
    series_tag: str
    processed: int
    updated: int
    membership_flagged: int = 0


class AppearanceService:
    def __init__(self, db: Session, extractor: AppearanceExtractor | None = None):
        self.db = db
        self.extractor = extractor or AppearanceExtractor()

    def _extra_series_tags(self, series: Series, character: Character) -> set[str]:
        extra: set[str] = {series.series_tag}
        if character.source_series_id:
            source = self.db.query(Series).filter(Series.id == character.source_series_id).first()
            if source:
                extra.add(source.series_tag)
        child_series = (
            self.db.query(Series.series_tag)
            .filter(Series.parent_series_id == series.id)
            .all()
        )
        extra.update(row[0] for row in child_series)
        return extra

    def _apply_membership_result(
        self,
        character: Character,
        membership,
    ) -> bool:
        if membership.is_mismatch and membership.reason:
            character.status = "needs_check"
            character.needs_check_reason = membership.reason
            return True

        if character.needs_check_reason and character.needs_check_reason.startswith(MEMBERSHIP_MISMATCH_PREFIX):
            character.needs_check_reason = None

        if membership.is_verified and character.status == "needs_check":
            character.status = "confirmed"

        return False

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
        membership_flagged = 0

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
            try:
                payload = self.extractor.client.get_related_tags(character.character_tag, category=0)
            except Exception as exc:
                raise RuntimeError(f"{character.character_tag}: {exc}") from exc

            related = parse_related_tags(payload)
            appearance = extract_appearance_tags(related)
            character.multi_color_hair = appearance.multi_color_hair
            character.hair_color = appearance.hair_color
            character.hair_shape = appearance.hair_shape
            character.eye_color = appearance.eye_color
            character.feature_tags = appearance.feature_tags
            character.gender = normalize_gender(appearance.gender)
            character.from_related = True
            character.appearance_confirmed = False
            character.generation_prompt = build_generation_prompt(character)

            membership = evaluate_series_membership(
                fetch_copyright_related_tags(self.extractor.client, character.character_tag),
                expected_series_tag=series.series_tag,
                extra_series_tags=self._extra_series_tags(series, character),
            )
            if self._apply_membership_result(character, membership):
                membership_flagged += 1

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

        series.last_appearance_updated = updated
        if total > 0 and updated == total and series.status in {"pending", "collecting", "collected"}:
            series.status = "tagged"

        self.db.commit()
        return AppearanceExtractResult(
            series_tag=series.series_tag,
            processed=total,
            updated=updated,
            membership_flagged=membership_flagged,
        )
