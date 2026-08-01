from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.integrations.danbooru.appearance_extractor import NO_HUMAN_TAGS, normalize_gender
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_review import GlobalCharacterReview
from app.services.db_write_queue import commit_db_session
from app.services.review_service import ReviewService

# ── 임계값(threshold)은 이 파일 한 곳에서만 관리한다 ─────────────────────
# 후보 판정과 추천 등급(-1/3) 로직이 여러 서비스에 흩어지지 않도록 중앙화.
CANDIDATE_SCORE_THRESHOLD = 0.5
HIGH_CONFIDENCE_SCORE_THRESHOLD = 0.6

GENDER_NO_HUMANS_SCORE = 0.6
GENDER_UNKNOWN_SCORE = 0.15
TAG_KEYWORD_SCORE = 0.5
FEATURE_TAG_KEYWORD_SCORE = 0.35
MISSING_APPEARANCE_SCORE = 0.2
NO_SERIES_LINK_SCORE = 0.1

FEMALE_LIKE_GENDER = "1girl"

PENDING_STATUS = "pending"
CONFIRMED_STATUS = "confirmed"
EXCLUDED_STATUS = "excluded"
DECIDED_STATUSES = (CONFIRMED_STATUS, EXCLUDED_STATUS)
NON_HUMAN_REVIEW_STATUSES = (PENDING_STATUS, CONFIRMED_STATUS, EXCLUDED_STATUS)

CONFIRMABLE_RATINGS = (-1, 3)

_NON_HUMAN_KEYWORDS = frozenset(NO_HUMAN_TAGS)
_TOKEN_SPLIT_RE = re.compile(r"[_,\s]+")


def _keyword_hits(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    tokens = {token for token in _TOKEN_SPLIT_RE.split(text.lower()) if token}
    return frozenset(tokens & _NON_HUMAN_KEYWORDS)


@dataclass(frozen=True)
class NonHumanEvaluation:
    score: float
    evidence: list[str] = field(default_factory=list)
    suggested_rating: int | None = None
    is_candidate: bool = False


def evaluate_non_human_candidate(character: GlobalCharacter) -> NonHumanEvaluation:
    """기존 gender 로직은 그대로 두고, 보조 신호만 더해 후보 점수를 산출한다.

    재수집 없이도 저장된 필드만으로 계산 가능해야 하므로 danbooru 재조회 없이
    character_tag/display_name/feature_tags/외형 태그/시리즈 연결 여부만 사용한다.
    """
    gender = normalize_gender(character.gender)
    evidence: list[str] = []
    score = 0.0

    if gender == "no_humans":
        score += GENDER_NO_HUMANS_SCORE
        evidence.append("gender:no_humans")
    elif gender is None:
        score += GENDER_UNKNOWN_SCORE
        evidence.append("gender:unknown")

    tag_hits = _keyword_hits(character.character_tag) | _keyword_hits(character.display_name)
    if tag_hits:
        score += TAG_KEYWORD_SCORE
        evidence.append(f"tag_keyword:{','.join(sorted(tag_hits))}")

    feature_hits = _keyword_hits(character.feature_tags)
    if feature_hits:
        score += FEATURE_TAG_KEYWORD_SCORE
        evidence.append(f"feature_keyword:{','.join(sorted(feature_hits))}")

    if gender in ("1girl", "1boy") and not any(
        (character.hair_color, character.eye_color, character.hair_shape, character.multi_color_hair)
    ):
        score += MISSING_APPEARANCE_SCORE
        evidence.append("missing_appearance_tags")

    if not character.series_links:
        score += NO_SERIES_LINK_SCORE
        evidence.append("no_series_membership")

    score = min(score, 1.0)
    is_candidate = score >= CANDIDATE_SCORE_THRESHOLD

    suggested_rating: int | None = None
    if is_candidate:
        if gender == FEMALE_LIKE_GENDER:
            suggested_rating = 3
        elif score >= HIGH_CONFIDENCE_SCORE_THRESHOLD:
            suggested_rating = -1

    return NonHumanEvaluation(
        score=score,
        evidence=evidence,
        suggested_rating=suggested_rating,
        is_candidate=is_candidate,
    )


def apply_recalculation(character: GlobalCharacter) -> bool:
    """확정/제외된 캐릭터는 건드리지 않는다 (사용자 결정 보존)."""
    if character.non_human_review_status in DECIDED_STATUSES:
        return False

    evaluation = evaluate_non_human_candidate(character)
    character.non_human_candidate_score = evaluation.score
    character.non_human_suggested_rating = evaluation.suggested_rating
    character.non_human_evidence = json.dumps(evaluation.evidence)
    character.non_human_calculated_at = datetime.now(timezone.utc)
    return True


@dataclass
class NonHumanRecalculateSummary:
    scanned: int = 0
    updated: int = 0
    candidate_count: int = 0
    skipped_decided: int = 0


RECALCULATE_BATCH_SIZE = 500


def recalculate_non_human_candidates(
    db: Session,
    *,
    character_tag: str | None = None,
    apply: bool = True,
) -> NonHumanRecalculateSummary:
    """로컬 데이터만으로 후보 점수를 재계산해 pending 큐를 채운다.

    Danbooru 등 외부 네트워크 조회 없이 이미 저장된 필드만 사용하므로 UI
    버튼에서 호출해도 안전한 동기 작업이다. candidate_count는 재계산 직후
    실제로 pending 큐에 노출될 행 수(상태가 pending이고 점수가 임계값 이상)를
    같은 in-memory 상태에서 집계한다.

    카탈로그 전체(수십만 행)를 단일 쿼리로 한 번에 파이썬 리스트에
    materialize하지 않도록 id 기준 keyset pagination으로 배치 처리한다 -
    한 번에 DB에서 가져와 메모리에 올리는 행 수를 배치 크기로 제한한다.
    session.expunge()는 쓰지 않는다: db는 호출자와 공유되는 세션이라
    (예: 라우터의 다른 코드나 호출자가 이미 들고 있는 GlobalCharacter
    인스턴스) 여기서 임의로 detach하면 호출자 쪽 참조가 깨질 수 있다.
    apply=True(UI 버튼 경로)면 배치마다 commit_db_session으로 커밋해
    SQLite 단일 writer 락을 다른 요청과 공정하게 나눠 쓰고, apply=False
    (dry-run, CLI 전용)면 어떤 배치도 커밋하지 않다가 끝까지 스캔한 뒤
    한 번에 rollback해 진짜 미리보기를 보장한다."""
    summary = NonHumanRecalculateSummary()
    last_id = 0
    while True:
        query = (
            db.query(GlobalCharacter)
            .options(selectinload(GlobalCharacter.series_links))
            .filter(GlobalCharacter.id > last_id)
        )
        if character_tag:
            query = query.filter(GlobalCharacter.character_tag == character_tag)

        batch = query.order_by(GlobalCharacter.id).limit(RECALCULATE_BATCH_SIZE).all()
        if not batch:
            break
        last_id = batch[-1].id

        for character in batch:
            summary.scanned += 1
            if apply_recalculation(character):
                summary.updated += 1
            else:
                summary.skipped_decided += 1

            if (
                character.non_human_review_status == PENDING_STATUS
                and (character.non_human_candidate_score or 0.0) >= CANDIDATE_SCORE_THRESHOLD
            ):
                summary.candidate_count += 1

        if apply:
            commit_db_session(db)

    if not apply:
        db.rollback()
    return summary


class NonHumanReviewService:
    """빠른 비인간(non-human) 프리뷰 큐 전용 서비스.

    최종 판단은 여전히 사용자 몫이며, 여기서는 후보 목록 조회와 confirm/exclude만
    다룬다. confirm은 기존 V2 리뷰 저장 로직(ReviewService.save_v2_review_character)을
    그대로 재사용해 정규 리뷰 데이터와의 정합성을 보장한다.
    """

    def __init__(self, db: Session):
        self.db = db
        self.review_service = ReviewService(db)

    def _base_query(self):
        return (
            self.db.query(GlobalCharacter)
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .options(
                joinedload(GlobalCharacter.images),
                joinedload(GlobalCharacter.review),
                joinedload(GlobalCharacter.parent),
                selectinload(GlobalCharacter.children),
                selectinload(GlobalCharacter.series_links).joinedload(CharacterSeriesLink.series),
            )
        )

    def list_candidates(
        self,
        *,
        filter_status: str = PENDING_STATUS,
        search: str | None = None,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[list[GlobalCharacter], int]:
        if filter_status not in (*NON_HUMAN_REVIEW_STATUSES, "all"):
            raise ValueError("filter_status must be one of pending, confirmed, excluded, all")

        query = self._base_query()
        if filter_status == PENDING_STATUS:
            query = query.filter(
                GlobalCharacter.non_human_review_status == PENDING_STATUS,
                GlobalCharacter.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD,
            )
        elif filter_status != "all":
            query = query.filter(GlobalCharacter.non_human_review_status == filter_status)

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    GlobalCharacter.character_tag.ilike(pattern),
                    GlobalCharacter.display_name.ilike(pattern),
                )
            )

        query = query.distinct()
        total = query.order_by(None).count()
        items = (
            query.order_by(
                GlobalCharacter.non_human_candidate_score.desc(),
                GlobalCharacter.post_count.desc(),
                GlobalCharacter.id.asc(),
            )
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def confirm(self, character_id: int, *, rating: int) -> GlobalCharacter:
        if rating not in CONFIRMABLE_RATINGS:
            raise ValueError("rating must be -1 or 3 for non-human confirmation")

        character = self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
        if not character:
            raise ValueError("Character not found")
        self._assert_actionable(character)

        # save_v2_review_character가 동일 세션에서 같은 row를 재조회하므로, 여기서 스테이징한
        # 변경이 그 커밋 한 번에 함께 반영되어 원자적으로 처리된다.
        character.non_human_review_status = CONFIRMED_STATUS

        return self.review_service.save_v2_review_character(
            character_id,
            review_status="completed",
            rating=rating,
        )

    def exclude(self, character_id: int) -> GlobalCharacter:
        character = (
            self.db.query(GlobalCharacter)
            .options(joinedload(GlobalCharacter.review))
            .filter(GlobalCharacter.id == character_id)
            .first()
        )
        if not character:
            raise ValueError("Character not found")
        self._assert_actionable(character)

        character.non_human_review_status = EXCLUDED_STATUS
        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    @staticmethod
    def _assert_actionable(character: GlobalCharacter) -> None:
        """confirm/exclude는 pending 상태의 진짜 후보에만 적용한다.

        이미 확정/제외된 결정을 덮어쓰거나, 임계값 미만인 캐릭터를 직접 API 호출로
        confirm/exclude하는 것을 막는다. 일반 V2 리뷰(별도 rating 변경 흐름)는
        이 제약과 무관하게 그대로 동작한다.
        """
        if character.non_human_review_status != PENDING_STATUS:
            raise ValueError(
                f"Cannot act on character with non_human_review_status="
                f"{character.non_human_review_status!r}; only 'pending' candidates can be confirmed/excluded"
            )
        if (character.non_human_candidate_score or 0.0) < CANDIDATE_SCORE_THRESHOLD:
            raise ValueError(
                "Character does not meet the non-human candidate score threshold for confirm/exclude"
            )
