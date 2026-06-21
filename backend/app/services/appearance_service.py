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
from app.integrations.danbooru.client import DanbooruAuthError
from app.integrations.danbooru.series_membership import (
    MEMBERSHIP_MISMATCH_PREFIX,
    evaluate_series_membership,
    fetch_copyright_related_tags,
)
from app.models.character import Character
from app.models.series import Series
from app.services.db_write_queue import commit_db_session
from app.services.prompt_service import build_generation_prompt
from app.services.settings_service import SettingsService

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

    @staticmethod
    def _can_auto_confirm(character: Character) -> bool:
        """Danbooru 데이터가 충분히 신뢰할 수 있는 경우 수동 검수 없이 자동 확정.

        기준:
        - 포스트 수 100 이상 (통계가 안정적)
        - 머리색·눈색 모두 추출됨 (핵심 외형 태그 존재)
        - 멤버십 불일치 없음 (호출 위치에서 mismatch가 False인 경우에만 호출됨)
        """
        return (
            character.post_count >= 100
            and bool(character.hair_color)
            and bool(character.eye_color)
        )

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
        min_post_count = SettingsService(self.db).get_min_character_post_count()

        all_characters = (
            self.db.query(Character)
            .filter(Character.series_id == series.id)
            .order_by(Character.character_tag.asc())
            .all()
        )
        # 포스트 수 임계값 이상 캐릭터만 추출 대상
        eligible_characters = [c for c in all_characters if c.post_count >= min_post_count]
        # 이미 추출 완료된 캐릭터는 건너뜀 (재시작 최적화)
        characters = [c for c in eligible_characters if not c.from_related]

        total = len(characters)
        eligible_total = len(eligible_characters)
        already_done = eligible_total - total
        updated = 0
        membership_flagged = 0

        if progress_callback:
            skip_msg = f" · {already_done}명 이미 완료" if already_done > 0 else ""
            progress_callback(
                {
                    "phase": "starting",
                    "message": f"{series.series_tag} 외형 태그 추출 시작 · {eligible_total}명 대상{skip_msg}",
                    "current": 0,
                    "total": total,
                }
            )

        for index, character in enumerate(characters, start=1):
            try:
                payload = self.extractor.client.get_related_tags(character.character_tag, category=0)
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
                elif self._can_auto_confirm(character):
                    # 충분한 데이터와 시리즈 소속이 확인된 경우 수동 검수 없이 자동 확정
                    character.appearance_confirmed = True
                    if character.status not in ("confirmed", "generated"):
                        character.status = "confirmed"

                updated += 1
            except DanbooruAuthError:
                raise
            except Exception as exc:
                if progress_callback:
                    progress_callback(
                        {
                            "phase": "extracting",
                            "message": f"외형 태그 추출 실패 (건너뜀) {index}/{total} · {character.character_tag} · {exc}",
                            "current": index,
                            "total": total,
                        }
                    )
                continue

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
        total_extracted = already_done + updated
        if eligible_total > 0 and total_extracted >= eligible_total and series.status in {"pending", "collecting", "collected"}:
            series.status = "tagged"

        commit_db_session(self.db)
        return AppearanceExtractResult(
            series_tag=series.series_tag,
            processed=total,
            updated=updated,
            membership_flagged=membership_flagged,
        )
