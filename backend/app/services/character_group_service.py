from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.character_link_suggestion import CharacterLinkSuggestion
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.services.character_link_service import CharacterLinkService
from app.services.db_write_queue import commit_db_session

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
SUPERSEDED = "superseded"
SUGGESTION_STATUSES = (PENDING, ACCEPTED, REJECTED, SUPERSEDED)

GROUP_STATE_CONFLICT = "conflict"
GROUP_STATE_PENDING = "pending"
GROUP_STATE_UNLINKED = "unlinked"
GROUP_STATE_SETTLED = "settled"
GROUP_STATE_ALL = "all"
_GROUP_STATE_ORDER = {
    GROUP_STATE_CONFLICT: 0,
    GROUP_STATE_PENDING: 1,
    GROUP_STATE_UNLINKED: 2,
    GROUP_STATE_SETTLED: 3,
}
GROUP_STATE_FILTERS = (
    GROUP_STATE_CONFLICT,
    GROUP_STATE_PENDING,
    GROUP_STATE_UNLINKED,
    GROUP_STATE_SETTLED,
    GROUP_STATE_ALL,
)

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_COMPLETED = "completed"
REVIEW_STATUS_ALL = "all"
REVIEW_STATUS_FILTERS = (REVIEW_STATUS_PENDING, REVIEW_STATUS_COMPLETED, REVIEW_STATUS_ALL)

_DEFAULT_RECALC_LIMIT = 30


@dataclass(frozen=True)
class GroupMemberPreview:
    character: GlobalCharacter
    review_status: str | None
    rating: int | None
    image_count: int
    preview_image_path: str | None
    is_cover_preview: bool


@dataclass(frozen=True)
class GroupSuggestionItem:
    id: int
    child: GroupMemberPreview
    score: float
    reason: str | None
    status: str


@dataclass(frozen=True)
class GroupDetail:
    parent: GroupMemberPreview
    children: list[GroupMemberPreview]
    suggestions: list[GroupSuggestionItem]
    state: str


@dataclass(frozen=True)
class GroupSummary:
    parent: GroupMemberPreview
    child_count: int
    pending_count: int
    state: str


@dataclass(frozen=True)
class GroupAction:
    op: str  # accept | add | reject | unlink | move
    child_id: int
    new_parent_id: int | None = None


@dataclass
class GroupRecalculateSummary:
    scanned_anchors: int = 0
    pending_total: int = 0
    accepted_total: int = 0
    rejected_total: int = 0
    superseded_total: int = 0


class CharacterGroupService:
    """부모 캐릭터를 앵커로 하는 부모/자식 병합 그룹(그룹 리뷰) 서비스.

    기존 `CharacterLinkService`의 추천/검증 로직을 그대로 재사용하고, 이 서비스는
    그 위에 durable suggestion(제안) 이력과 그룹 단위 조회/일괄 적용만 추가한다.
    """

    def __init__(self, db: Session):
        self.db = db
        self.link_service = CharacterLinkService(db)

    # ── 내부 조회 헬퍼 ──────────────────────────────────────────────

    def _get_character(self, character_id: int) -> GlobalCharacter | None:
        return self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()

    def _get_suggestion(self, parent_id: int, child_id: int) -> CharacterLinkSuggestion | None:
        return (
            self.db.query(CharacterLinkSuggestion)
            .filter(
                CharacterLinkSuggestion.parent_character_id == parent_id,
                CharacterLinkSuggestion.child_character_id == child_id,
            )
            .first()
        )

    def _upsert_suggestion(
        self,
        parent_id: int,
        child_id: int,
        *,
        status: str,
        score: float | None = None,
        reason: str | None = None,
        decided: bool = False,
    ) -> CharacterLinkSuggestion:
        row = self._get_suggestion(parent_id, child_id)
        if row is None:
            row = CharacterLinkSuggestion(
                parent_character_id=parent_id,
                child_character_id=child_id,
                score=score if score is not None else 0.0,
                reason=reason,
                status=status,
            )
            self.db.add(row)
        else:
            if score is not None:
                row.score = score
            if reason is not None:
                row.reason = reason
            row.status = status
        if decided:
            row.decided_at = datetime.now(timezone.utc)
        return row

    def _classify_state(self, *, child_count: int, pending_count: int, is_conflicted: bool) -> str:
        if is_conflicted:
            return GROUP_STATE_CONFLICT
        if pending_count > 0:
            return GROUP_STATE_PENDING
        if child_count == 0:
            return GROUP_STATE_UNLINKED
        return GROUP_STATE_SETTLED

    def _conflicted_parents_among(self, parent_ids: set[int]) -> set[int]:
        """`parent_ids` 범위 내에서, 같은 자식이 서로 다른 부모에게 동시에 pending
        상태로 제안된 경우(모호한 그룹핑) 해당 부모 id 집합을 반환한다."""
        if not parent_ids:
            return set()
        rows = (
            self.db.query(CharacterLinkSuggestion.child_character_id, CharacterLinkSuggestion.parent_character_id)
            .filter(
                CharacterLinkSuggestion.status == PENDING,
                CharacterLinkSuggestion.parent_character_id.in_(parent_ids),
            )
            .all()
        )
        by_child: dict[int, set[int]] = {}
        for child_id, parent_id in rows:
            by_child.setdefault(child_id, set()).add(parent_id)
        conflicted: set[int] = set()
        for parents in by_child.values():
            if len(parents) > 1:
                conflicted |= parents
        return conflicted

    def _conflicted_parents_for_children(self, child_ids: set[int]) -> set[int]:
        if not child_ids:
            return set()
        rows = (
            self.db.query(CharacterLinkSuggestion.child_character_id, CharacterLinkSuggestion.parent_character_id)
            .filter(
                CharacterLinkSuggestion.status == PENDING,
                CharacterLinkSuggestion.child_character_id.in_(child_ids),
            )
            .all()
        )
        by_child: dict[int, set[int]] = {}
        for child_id, parent_id in rows:
            by_child.setdefault(child_id, set()).add(parent_id)
        conflicted: set[int] = set()
        for parents in by_child.values():
            if len(parents) > 1:
                conflicted |= parents
        return conflicted

    def _build_previews(self, character_ids: list[int]) -> dict[int, GroupMemberPreview]:
        unique_ids = list(dict.fromkeys(character_ids))
        if not unique_ids:
            return {}

        characters = self.db.query(GlobalCharacter).filter(GlobalCharacter.id.in_(unique_ids)).all()
        char_map = {character.id: character for character in characters}

        reviews = (
            self.db.query(GlobalCharacterReview)
            .filter(GlobalCharacterReview.global_character_id.in_(unique_ids))
            .all()
        )
        review_map = {review.global_character_id: review for review in reviews}

        image_count_map = dict(
            self.db.query(GlobalCharacterImage.global_character_id, func.count(GlobalCharacterImage.id))
            .filter(GlobalCharacterImage.global_character_id.in_(unique_ids))
            .group_by(GlobalCharacterImage.global_character_id)
            .all()
        )

        cover_ids = {
            review.cover_image_id
            for review in reviews
            if review.cover_image_id and review.review_status == "completed"
        }
        cover_path_by_image_id: dict[int, str] = {}
        if cover_ids:
            cover_images = self.db.query(GlobalCharacterImage).filter(GlobalCharacterImage.id.in_(cover_ids)).all()
            cover_path_by_image_id = {image.id: image.image_path for image in cover_images}
        cover_map = {
            review.global_character_id: cover_path_by_image_id[review.cover_image_id]
            for review in reviews
            if review.review_status == "completed" and review.cover_image_id in cover_path_by_image_id
        }

        # cover가 없으면 가장 최근 생성된 이미지로 대체(cover-or-latest).
        latest_rows = (
            self.db.query(
                GlobalCharacterImage.global_character_id,
                GlobalCharacterImage.image_path,
                GlobalCharacterImage.id,
            )
            .filter(GlobalCharacterImage.global_character_id.in_(unique_ids))
            .order_by(GlobalCharacterImage.global_character_id, GlobalCharacterImage.id.desc())
            .all()
        )
        latest_map: dict[int, str] = {}
        for character_id, image_path, _image_id in latest_rows:
            latest_map.setdefault(character_id, image_path)

        previews: dict[int, GroupMemberPreview] = {}
        for character_id, character in char_map.items():
            review = review_map.get(character_id)
            preview_path = cover_map.get(character_id) or latest_map.get(character_id)
            previews[character_id] = GroupMemberPreview(
                character=character,
                review_status=review.review_status if review else None,
                rating=review.rating if review else None,
                image_count=image_count_map.get(character_id, 0),
                preview_image_path=preview_path,
                is_cover_preview=character_id in cover_map,
            )
        return previews

    # ── 재계산(recalculation) ────────────────────────────────────────

    def recalculate_group(self, anchor: GlobalCharacter, *, limit: int = _DEFAULT_RECALC_LIMIT) -> None:
        """이 앵커 하나에 대해서만 추천 후보를 다시 계산해 suggestion 행을
        upsert한다. 커밋은 호출자가 담당한다 (단일 그룹 조회 시 동기 실행,
        전체 재계산 CLI에서는 루프 안에서 여러 번 호출된다).

        사용자가 이미 거부(rejected)한 쌍은 절대 건드리지 않는다.
        """
        if anchor.parent_character_id is not None:
            # 자식은 그룹 앵커(부모)가 될 수 없다 (1단계 깊이 제약).
            return

        ranked = self.link_service.list_child_candidates(anchor, limit=limit)
        candidate_ids: set[int] = set()
        for item in ranked:
            candidate = item.character
            if candidate.id == anchor.id:
                continue
            if candidate.parent_character_id == anchor.id:
                # 이미 실제로 연결된 자식 - 더 이상 제안이 필요 없다.
                continue
            if not self.link_service.candidate_is_linkable(candidate, role="child"):
                continue

            candidate_ids.add(candidate.id)
            existing = self._get_suggestion(anchor.id, candidate.id)
            if existing is None:
                self.db.add(
                    CharacterLinkSuggestion(
                        parent_character_id=anchor.id,
                        child_character_id=candidate.id,
                        score=item.similarity_score,
                        reason=item.match_reason or None,
                        status=PENDING,
                    )
                )
            elif existing.status == REJECTED:
                continue  # 사용자 거부 이력 보존
            elif existing.status == ACCEPTED:
                continue  # 이미 확정된 연결 (정상적으로는 후보 쿼리에서 걸러짐)
            else:  # pending 또는 superseded -> 최신 점수로 갱신/부활
                existing.score = item.similarity_score
                existing.reason = item.match_reason or None
                existing.status = PENDING

        stale = (
            self.db.query(CharacterLinkSuggestion)
            .filter(
                CharacterLinkSuggestion.parent_character_id == anchor.id,
                CharacterLinkSuggestion.status == PENDING,
                ~CharacterLinkSuggestion.child_character_id.in_(candidate_ids),
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for row in stale:
            row.status = SUPERSEDED
            row.decided_at = now

    def recalculate_all(
        self,
        *,
        character_tag: str | None = None,
        apply: bool = True,
        limit_per_anchor: int = _DEFAULT_RECALC_LIMIT,
    ) -> GroupRecalculateSummary:
        """전체 캐릭터를 대상으로 한 무거운 재계산. HTTP 요청 경로에서는 절대
        호출하지 않고, `scripts/v2_recalculate_character_link_suggestions.py`
        유지보수 CLI에서만 사용한다."""
        query = self.db.query(GlobalCharacter).filter(GlobalCharacter.parent_character_id.is_(None))
        if character_tag:
            query = query.filter(GlobalCharacter.character_tag == character_tag)

        summary = GroupRecalculateSummary()
        for anchor in query.order_by(GlobalCharacter.id).all():
            self.recalculate_group(anchor, limit=limit_per_anchor)
            summary.scanned_anchors += 1

        counts = dict(
            self.db.query(CharacterLinkSuggestion.status, func.count(CharacterLinkSuggestion.id))
            .group_by(CharacterLinkSuggestion.status)
            .all()
        )
        summary.pending_total = counts.get(PENDING, 0)
        summary.accepted_total = counts.get(ACCEPTED, 0)
        summary.rejected_total = counts.get(REJECTED, 0)
        summary.superseded_total = counts.get(SUPERSEDED, 0)

        if apply:
            commit_db_session(self.db)
        else:
            self.db.rollback()
        return summary

    # ── 조회 ──────────────────────────────────────────────────────

    def list_groups(
        self,
        *,
        search: str | None = None,
        state: str | None = None,
        has_image: bool | None = None,
        review_status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[GroupSummary], int]:
        """DB 레벨에서 정렬/페이지네이션을 수행한다. 전체 앵커를 파이썬으로
        로드/정렬하지 않고, 상태 우선순위(conflict > pending > unlinked >
        settled) 계산과 LIMIT/OFFSET을 모두 SQL에 위임한 뒤, 결과 페이지에
        대해서만 미리보기(preview)를 조회한다.

        `state`/`has_image`/`review_status`는 부모(앵커) 카드 기준 필터로,
        모두 EXISTS/서브쿼리를 통해 DB 레벨에서 적용된다 (카탈로그 전체를
        파이썬으로 materialize하지 않음)."""
        child_counts_sq = (
            self.db.query(
                GlobalCharacter.parent_character_id.label("parent_id"),
                func.count(GlobalCharacter.id).label("child_count"),
            )
            .filter(GlobalCharacter.parent_character_id.isnot(None))
            .group_by(GlobalCharacter.parent_character_id)
            .subquery()
        )
        pending_counts_sq = (
            self.db.query(
                CharacterLinkSuggestion.parent_character_id.label("parent_id"),
                func.count(CharacterLinkSuggestion.id).label("pending_count"),
            )
            .filter(CharacterLinkSuggestion.status == PENDING)
            .group_by(CharacterLinkSuggestion.parent_character_id)
            .subquery()
        )
        # pending 제안만 앵커 후보로 인정한다: rejected/superseded는 이력일 뿐이며
        # accepted는 실제 parent_character_id 관계(child_counts_sq)로 이미 발견된다.
        # 그렇지 않으면 거부/대체된 과거 제안만 남은 캐릭터가 그룹 목록에 유령
        # 앵커로 계속 노출된다.
        suggestion_parents_sq = (
            self.db.query(CharacterLinkSuggestion.parent_character_id.label("parent_id"))
            .filter(CharacterLinkSuggestion.status == PENDING)
            .distinct()
            .subquery()
        )
        multi_parent_children_sq = (
            self.db.query(CharacterLinkSuggestion.child_character_id.label("child_id"))
            .filter(CharacterLinkSuggestion.status == PENDING)
            .group_by(CharacterLinkSuggestion.child_character_id)
            .having(func.count(func.distinct(CharacterLinkSuggestion.parent_character_id)) > 1)
            .subquery()
        )
        conflicted_parents_sq = (
            self.db.query(CharacterLinkSuggestion.parent_character_id.label("parent_id"))
            .filter(
                CharacterLinkSuggestion.status == PENDING,
                CharacterLinkSuggestion.child_character_id.in_(
                    self.db.query(multi_parent_children_sq.c.child_id)
                ),
            )
            .distinct()
            .subquery()
        )

        child_count_col = func.coalesce(child_counts_sq.c.child_count, 0)
        pending_count_col = func.coalesce(pending_counts_sq.c.pending_count, 0)
        is_conflicted_col = conflicted_parents_sq.c.parent_id.isnot(None)
        state_rank_col = case(
            (is_conflicted_col, _GROUP_STATE_ORDER[GROUP_STATE_CONFLICT]),
            (pending_count_col > 0, _GROUP_STATE_ORDER[GROUP_STATE_PENDING]),
            (child_count_col == 0, _GROUP_STATE_ORDER[GROUP_STATE_UNLINKED]),
            else_=_GROUP_STATE_ORDER[GROUP_STATE_SETTLED],
        )

        base_query = (
            self.db.query(
                GlobalCharacter,
                child_count_col.label("child_count"),
                pending_count_col.label("pending_count"),
                is_conflicted_col.label("is_conflicted"),
            )
            .outerjoin(child_counts_sq, child_counts_sq.c.parent_id == GlobalCharacter.id)
            .outerjoin(pending_counts_sq, pending_counts_sq.c.parent_id == GlobalCharacter.id)
            .outerjoin(conflicted_parents_sq, conflicted_parents_sq.c.parent_id == GlobalCharacter.id)
            .filter(
                or_(
                    GlobalCharacter.id.in_(self.db.query(child_counts_sq.c.parent_id)),
                    GlobalCharacter.id.in_(self.db.query(suggestion_parents_sq.c.parent_id)),
                )
            )
        )
        if search:
            like = f"%{search.strip()}%"
            base_query = base_query.filter(
                or_(GlobalCharacter.character_tag.ilike(like), GlobalCharacter.display_name.ilike(like))
            )

        if state and state != GROUP_STATE_ALL:
            if state == GROUP_STATE_CONFLICT:
                base_query = base_query.filter(is_conflicted_col)
            elif state == GROUP_STATE_PENDING:
                base_query = base_query.filter(~is_conflicted_col, pending_count_col > 0)
            elif state == GROUP_STATE_UNLINKED:
                base_query = base_query.filter(~is_conflicted_col, pending_count_col == 0, child_count_col == 0)
            elif state == GROUP_STATE_SETTLED:
                base_query = base_query.filter(~is_conflicted_col, pending_count_col == 0, child_count_col > 0)
            else:
                raise ValueError(f"Unsupported state filter: {state}")

        if has_image is not None:
            image_exists = exists(select(1).where(GlobalCharacterImage.global_character_id == GlobalCharacter.id))
            base_query = base_query.filter(image_exists if has_image else ~image_exists)

        if review_status and review_status != REVIEW_STATUS_ALL:
            completed_exists = exists(
                select(1).where(
                    GlobalCharacterReview.global_character_id == GlobalCharacter.id,
                    GlobalCharacterReview.review_status == REVIEW_STATUS_COMPLETED,
                )
            )
            if review_status == REVIEW_STATUS_COMPLETED:
                base_query = base_query.filter(completed_exists)
            elif review_status == REVIEW_STATUS_PENDING:
                base_query = base_query.filter(~completed_exists)
            else:
                raise ValueError(f"Unsupported review_status filter: {review_status}")

        total = base_query.order_by(None).count()
        if total == 0:
            return [], 0

        rows = (
            base_query.order_by(
                state_rank_col.asc(),
                pending_count_col.desc(),
                GlobalCharacter.post_count.desc(),
                GlobalCharacter.character_tag.asc(),
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

        anchor_ids_page = [row[0].id for row in rows]
        previews = self._build_previews(anchor_ids_page)

        summaries: list[GroupSummary] = []
        for anchor, child_count, pending_count, is_conflicted in rows:
            state = self._classify_state(
                child_count=child_count, pending_count=pending_count, is_conflicted=bool(is_conflicted)
            )
            summaries.append(
                GroupSummary(
                    parent=previews[anchor.id],
                    child_count=child_count,
                    pending_count=pending_count,
                    state=state,
                )
            )

        return summaries, total

    def _build_detail(self, anchor: GlobalCharacter) -> GroupDetail:
        children = (
            self.db.query(GlobalCharacter)
            .filter(GlobalCharacter.parent_character_id == anchor.id)
            .order_by(GlobalCharacter.character_tag.asc())
            .all()
        )
        suggestions = (
            self.db.query(CharacterLinkSuggestion)
            .filter(
                CharacterLinkSuggestion.parent_character_id == anchor.id,
                CharacterLinkSuggestion.status == PENDING,
            )
            .order_by(CharacterLinkSuggestion.score.desc())
            .all()
        )

        child_ids = [child.id for child in children]
        suggestion_child_ids = [suggestion.child_character_id for suggestion in suggestions]
        previews = self._build_previews([anchor.id, *child_ids, *suggestion_child_ids])

        conflicted_ids = self._conflicted_parents_for_children(set(suggestion_child_ids))
        state = self._classify_state(
            child_count=len(children), pending_count=len(suggestions), is_conflicted=anchor.id in conflicted_ids
        )

        return GroupDetail(
            parent=previews[anchor.id],
            children=[previews[child.id] for child in children],
            suggestions=[
                GroupSuggestionItem(
                    id=suggestion.id,
                    child=previews[suggestion.child_character_id],
                    score=suggestion.score,
                    reason=suggestion.reason,
                    status=suggestion.status,
                )
                for suggestion in suggestions
                if suggestion.child_character_id in previews
            ],
            state=state,
        )

    def get_group(self, anchor_id: int, *, recalc: bool = False) -> GroupDetail | None:
        anchor = self._get_character(anchor_id)
        if anchor is None:
            return None
        if recalc:
            self.recalculate_group(anchor)
            commit_db_session(self.db)
            self.db.refresh(anchor)
        return self._build_detail(anchor)

    # ── 그룹 일괄 적용(apply) ────────────────────────────────────────

    def _accept(self, anchor: GlobalCharacter, child: GlobalCharacter) -> None:
        if anchor.id == child.id:
            raise ValueError("Cannot link a character to itself.")
        self.link_service._ensure_child_candidate(child)
        self.link_service._ensure_parent_candidate(anchor)
        child.parent_character_id = anchor.id
        self._upsert_suggestion(anchor.id, child.id, status=ACCEPTED, decided=True)

    def _reject(self, anchor: GlobalCharacter, child: GlobalCharacter) -> None:
        if anchor.id == child.id:
            raise ValueError("Cannot reject a character against itself.")
        if child.parent_character_id == anchor.id:
            raise ValueError("Character is already linked to this parent; use unlink instead.")
        self._upsert_suggestion(anchor.id, child.id, status=REJECTED, decided=True)

    def _unlink(self, anchor: GlobalCharacter, child: GlobalCharacter) -> None:
        if child.parent_character_id != anchor.id:
            raise ValueError("Character is not linked to this parent.")
        child.parent_character_id = None
        # superseded 처리 -> 다음 재계산 시 다시 후보로 떠오를 수 있다 (거부와는 구분).
        self._upsert_suggestion(anchor.id, child.id, status=SUPERSEDED, decided=True)

    def _move(self, child: GlobalCharacter, new_parent: GlobalCharacter) -> None:
        if child.id == new_parent.id:
            raise ValueError("Cannot link a character to itself.")
        if self.link_service._child_count(child.id) > 0:
            raise ValueError("Character with its own children cannot be linked under another parent.")
        self.link_service._ensure_parent_candidate(new_parent)

        old_parent_id = child.parent_character_id
        if old_parent_id is not None and old_parent_id != new_parent.id:
            self._upsert_suggestion(old_parent_id, child.id, status=SUPERSEDED, decided=True)

        child.parent_character_id = new_parent.id
        self._upsert_suggestion(new_parent.id, child.id, status=ACCEPTED, decided=True)

    def _apply_one(self, anchor: GlobalCharacter, action: GroupAction) -> None:
        child = self._get_character(action.child_id)
        if child is None:
            raise ValueError(f"Character not found: {action.child_id}")

        if action.op in ("accept", "add"):
            self._accept(anchor, child)
        elif action.op == "reject":
            self._reject(anchor, child)
        elif action.op == "unlink":
            self._unlink(anchor, child)
        elif action.op == "move":
            if action.new_parent_id is None:
                raise ValueError("new_parent_id is required for move")
            if child.parent_character_id != anchor.id:
                raise ValueError("Character must belong to this group before it can be moved.")
            new_parent = self._get_character(action.new_parent_id)
            if new_parent is None:
                raise ValueError(f"Character not found: {action.new_parent_id}")
            self._move(child, new_parent)
        else:
            raise ValueError(f"Unsupported action: {action.op}")

    def apply_actions(self, anchor_id: int, actions: list[GroupAction]) -> GroupDetail:
        """그룹의 모든 액션을 한 트랜잭션으로 처리한다. 하나라도 검증에 실패하면
        전체를 롤백한다 (그룹 전체가 일관된 상태로만 커밋된다)."""
        anchor = self._get_character(anchor_id)
        if anchor is None:
            raise ValueError("Character not found")

        try:
            for action in actions:
                self._apply_one(anchor, action)
                # 프로덕션 SessionLocal은 autoflush=False이므로, 이후 액션의 SQL
                # 검증(예: _child_count)이 앞선 액션에서 스테이징된 변경을 보도록
                # 매 액션 뒤에 명시적으로 flush한다. 배치 전체는 여전히 하나의
                # 트랜잭션이라 롤백 시 모두 되돌아간다.
                self.db.flush()
            commit_db_session(self.db)
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(anchor)
        return self._build_detail(anchor)
