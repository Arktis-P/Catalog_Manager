from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.integrations.danbooru.client import DanbooruClient
from app.models.character import Character
from app.models.series import Series
from app.services.collect_job_manager import series_job_manager
from app.services.db_write_queue import commit_db_session

MERGEABLE_STATUSES = frozenset({"collected", "tagged"})


@dataclass
class MergePreview:
    child_series_id: int
    child_series_tag: str
    parent_series_id: int
    parent_series_tag: str
    child_character_count: int
    duplicate_count: int
    moved_count: int


@dataclass
class MergeResult:
    child_series_id: int
    child_series_tag: str
    parent_series_id: int
    parent_series_tag: str
    moved_count: int
    duplicate_count: int
    parent_character_count: int


@dataclass
class UnmergeResult:
    child_series_id: int
    child_series_tag: str
    moved_back_count: int
    child_character_count: int


def _escape_like_pattern(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _normalize_tag(value: str) -> str:
    cleaned = re.sub(r"[()]", " ", value.lower())
    cleaned = re.sub(r"[_\-/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tag_tokens(value: str) -> set[str]:
    tokens = set(_normalize_tag(value).split())
    return {token for token in tokens if len(token) >= 2}


def similarity_score(left: Series, right: Series) -> float:
    if left.id == right.id:
        return -1.0

    left_tag = left.series_tag.lower()
    right_tag = right.series_tag.lower()
    if left_tag in right_tag or right_tag in left_tag:
        return 0.95

    left_tokens = _tag_tokens(left.series_tag) | _tag_tokens(left.display_name or "")
    right_tokens = _tag_tokens(right.series_tag) | _tag_tokens(right.display_name or "")
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(len(left_tokens), len(right_tokens))


def max_similarity_score(anchors: list[Series], target: Series) -> float:
    if not anchors:
        return 0.0
    return max(similarity_score(a, target) for a in anchors)


class SeriesMergeService:
    def __init__(self, db: Session):
        self.db = db

    def _get_series(self, series_id: int) -> Series | None:
        return self.db.query(Series).filter(Series.id == series_id).first()

    def _parent_has_catalog(self, series: Series) -> bool:
        character_count = self.db.query(Character.id).filter(Character.series_id == series.id).count()
        if character_count > 0:
            return True
        child_count = self.db.query(Series.id).filter(Series.parent_series_id == series.id).count()
        return child_count > 0

    def _ensure_mergeable(self, series: Series, *, role: str) -> None:
        role_key = role.lower()
        if series.status in MERGEABLE_STATUSES:
            pass
        elif role_key == "parent" and series.status == "pending" and self._parent_has_catalog(series):
            pass
        else:
            raise ValueError(f"{role} series must be collected or tagged before merging.")
        if series_job_manager.get_active_job_for_series(series.id):
            raise ValueError(f"{role} series has an active collect/appearance job.")

    def _ensure_parent_candidate(self, series: Series) -> None:
        if series.parent_series_id is not None:
            raise ValueError("Parent series cannot already be merged into another series.")

    def _ensure_child_candidate(self, series: Series) -> None:
        if series.parent_series_id is not None:
            raise ValueError("Series is already merged into another series.")
        child_count = self.db.query(Series.id).filter(Series.parent_series_id == series.id).count()
        if child_count > 0:
            raise ValueError("Series with sub-series cannot be merged into another series.")

    @staticmethod
    def _rank_recommendations(
        anchors: list[Series],
        candidates: list[Series],
        *,
        limit: int,
        has_children_ids: set[int] | None = None,
    ) -> list[Series]:
        def sort_key(item: Series) -> tuple[float, int, int, str]:
            sim = max_similarity_score(anchors, item)
            has_children = 1 if (has_children_ids and item.id in has_children_ids) else 0
            return (-sim, -has_children, -item.post_count, item.series_tag.lower())

        ranked = sorted(candidates, key=sort_key)
        similar = [item for item in ranked if max_similarity_score(anchors, item) > 0]
        return similar[:limit] if similar else ranked[:limit]

    @staticmethod
    def _rank_search_results(candidates: list[Series], *, limit: int) -> list[Series]:
        ranked = sorted(candidates, key=lambda item: (-item.post_count, item.series_tag.lower()))
        return ranked[:limit]

    def candidate_is_mergeable(
        self,
        series: Series,
        *,
        role: str,
        character_count: int = 0,
    ) -> bool:
        if series_job_manager.get_active_job_for_series(series.id):
            return False
        if series.status in MERGEABLE_STATUSES:
            return True
        if role == "parent" and series.status == "pending":
            if character_count > 0:
                return True
            return self._parent_has_catalog(series)
        return False

    def _base_candidate_query(
        self,
        anchor: Series,
        *,
        exclude_ids: set[int] | None = None,
        mergeable_only: bool,
    ):
        query = self.db.query(Series).filter(
            Series.id != anchor.id,
            Series.parent_series_id.is_(None),
        )
        if mergeable_only:
            query = query.filter(Series.status.in_(MERGEABLE_STATUSES))
        if exclude_ids:
            query = query.filter(~Series.id.in_(exclude_ids))
        return query

    def _find_exact_tag_match(self, search: str) -> Series | None:
        term = search.strip()
        if not term:
            return None
        return (
            self.db.query(Series)
            .filter(func.lower(Series.series_tag) == term.lower())
            .first()
        )

    @staticmethod
    def _inject_exact_match(candidates: list[Series], exact: Series | None, *, limit: int) -> list[Series]:
        if not exact:
            return candidates[:limit]
        merged = [exact, *[item for item in candidates if item.id != exact.id]]
        return merged[:limit]

    def _search_candidates(
        self,
        query,
        *,
        search: str,
        limit: int,
        exact: Series | None,
    ) -> list[Series]:
        search_lower = search.strip().lower()
        filtered = query.filter(
            or_(
                func.instr(func.lower(Series.series_tag), search_lower) > 0,
                func.instr(func.lower(Series.display_name), search_lower) > 0,
            )
        ).order_by(Series.post_count.desc(), Series.series_tag.asc())
        ranked = self._rank_search_results(filtered.limit(limit).all(), limit=limit)
        return self._inject_exact_match(ranked, exact, limit=limit)

    def _fetch_text_similar(self, anchors: list[Series], *, known_ids: set[int]) -> list[Series]:
        """top-N 풀에 포함되지 않은 이름 유사 시리즈를 추가로 조회한다."""
        tokens: set[str] = set()
        for anchor in anchors:
            tokens |= _tag_tokens(anchor.series_tag)
            if anchor.display_name:
                tokens |= _tag_tokens(anchor.display_name)
        top_tokens = sorted(tokens, key=len, reverse=True)[:4]
        if not top_tokens:
            return []

        found: dict[int, Series] = {}
        for token in top_tokens:
            token_lower = token.lower()
            base = self.db.query(Series).filter(
                Series.parent_series_id.is_(None),
                or_(
                    func.instr(func.lower(Series.series_tag), token_lower) > 0,
                    func.instr(func.lower(Series.display_name), token_lower) > 0,
                ),
            )
            if known_ids:
                base = base.filter(~Series.id.in_(known_ids))
            for row in base.limit(100).all():
                found[row.id] = row
        return list(found.values())

    def _list_candidates(
        self,
        anchor: Series,
        *,
        role: str,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
        source_series: list[Series] | None = None,
    ) -> list[Series]:
        anchors = source_series if source_series else [anchor]
        mergeable_only = role == "child"
        query = self._base_candidate_query(anchor, exclude_ids=exclude_ids, mergeable_only=mergeable_only)

        if search:
            exact = self._find_exact_tag_match(search)
            if exact and (
                exact.id == anchor.id
                or exact.parent_series_id is not None
                or (exclude_ids and exact.id in exclude_ids)
            ):
                exact = None
            return self._search_candidates(query, search=search, limit=limit, exact=exact)

        ordered = query.order_by(Series.post_count.desc(), Series.series_tag.asc())
        pool_size = max(limit * 8, 400)
        candidates = ordered.limit(pool_size).all()

        if role == "child":
            series_with_children = {
                row[0]
                for row in self.db.query(Series.parent_series_id)
                .filter(Series.parent_series_id.isnot(None))
                .distinct()
                .all()
                if row[0] is not None
            }
            candidates = [item for item in candidates if item.id not in series_with_children]
            return self._rank_recommendations(anchors, candidates, limit=limit)

        # parent mode: 포스트 수 상위 풀 + 이름 유사 시리즈로 풀 확장
        pool_ids: set[int] = {c.id for c in candidates}
        exclude_for_text = pool_ids | (exclude_ids or set()) | {anchor.id}
        extra = self._fetch_text_similar(anchors, known_ids=exclude_for_text)
        all_candidates = candidates + extra

        all_candidate_ids = [c.id for c in all_candidates]
        has_children_ids: set[int] = set()
        if all_candidate_ids:
            has_children_ids = {
                row[0]
                for row in self.db.query(Series.parent_series_id)
                .filter(Series.parent_series_id.in_(all_candidate_ids))
                .distinct()
                .all()
                if row[0] is not None
            }
        return self._rank_recommendations(anchors, all_candidates, limit=limit, has_children_ids=has_children_ids)

    def list_parent_candidates(
        self,
        child: Series,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
        source_series: list[Series] | None = None,
    ) -> list[Series]:
        return self._list_candidates(
            child,
            role="parent",
            search=search,
            limit=limit,
            exclude_ids=exclude_ids,
            source_series=source_series,
        )

    def list_child_candidates(
        self,
        parent: Series,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[Series]:
        return self._list_candidates(
            parent,
            role="child",
            search=search,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    def preview_merge(self, child_id: int, parent_id: int) -> MergePreview:
        child = self._get_series(child_id)
        parent = self._get_series(parent_id)
        if not child or not parent:
            raise ValueError("Series not found.")
        if child.id == parent.id:
            raise ValueError("Cannot merge a series into itself.")

        self._ensure_mergeable(child, role="Child")
        self._ensure_mergeable(parent, role="Parent")
        self._ensure_child_candidate(child)
        self._ensure_parent_candidate(parent)

        child_characters = (
            self.db.query(Character.character_tag)
            .filter(Character.series_id == child.id)
            .all()
        )
        child_tags = [row[0] for row in child_characters]
        duplicate_count = 0
        if child_tags:
            duplicate_count = (
                self.db.query(Character.id)
                .filter(Character.series_id == parent.id, Character.character_tag.in_(child_tags))
                .count()
            )
        moved_count = len(child_tags) - duplicate_count
        return MergePreview(
            child_series_id=child.id,
            child_series_tag=child.series_tag,
            parent_series_id=parent.id,
            parent_series_tag=parent.series_tag,
            child_character_count=len(child_tags),
            duplicate_count=duplicate_count,
            moved_count=moved_count,
        )

    def merge_into_parent(self, child_id: int, parent_id: int) -> MergeResult:
        preview = self.preview_merge(child_id, parent_id)
        child = self._get_series(child_id)
        parent = self._get_series(parent_id)
        if not child or not parent:
            raise ValueError("Series not found.")

        parent_tags = {
            row[0]
            for row in self.db.query(Character.character_tag).filter(Character.series_id == parent.id).all()
        }
        child_characters = (
            self.db.query(Character)
            .filter(Character.series_id == child.id)
            .order_by(Character.character_tag.asc())
            .all()
        )

        moved_count = 0
        duplicate_count = 0

        for character in child_characters:
            if character.character_tag in parent_tags:
                duplicate_count += 1
                self.db.delete(character)
                continue

            character.series_id = parent.id
            character.source_series_id = child.id
            character.danbooru_url = DanbooruClient.build_danbooru_url(
                character.character_tag,
                parent.series_tag,
            )
            character.status = "needs_check"
            character.needs_check_reason = f"Merged from sub-series '{child.series_tag}'"
            parent_tags.add(character.character_tag)
            moved_count += 1

        child.parent_series_id = parent.id
        child.merged_moved_count = moved_count
        child.merged_duplicate_count = duplicate_count
        child.status = "disabled"
        child.note = (child.note or "").strip()
        merge_note = f"Merged into {parent.series_tag}"
        child.note = f"{child.note} | {merge_note}" if child.note else merge_note

        parent_character_count = (
            self.db.query(Character.id).filter(Character.series_id == parent.id).count()
        )
        if parent.status == "pending" and parent_character_count > 0:
            parent.status = "collected"

        commit_db_session(self.db)
        self.db.refresh(parent)

        return MergeResult(
            child_series_id=child.id,
            child_series_tag=child.series_tag,
            parent_series_id=parent.id,
            parent_series_tag=parent.series_tag,
            moved_count=moved_count,
            duplicate_count=duplicate_count,
            parent_character_count=parent_character_count,
        )

    def unmerge(self, child_id: int) -> UnmergeResult:
        child = self._get_series(child_id)
        if not child:
            raise ValueError("Series not found.")
        if child.parent_series_id is None:
            raise ValueError("Series is not merged into another series.")
        if series_job_manager.get_active_job_for_series(child.id):
            raise ValueError("Cannot unmerge while a job is active on this series.")
        parent_id = child.parent_series_id
        if series_job_manager.get_active_job_for_series(parent_id):
            raise ValueError("Cannot unmerge while a job is active on the parent series.")

        moved_back = (
            self.db.query(Character)
            .filter(Character.series_id == parent_id, Character.source_series_id == child.id)
            .order_by(Character.character_tag.asc())
            .all()
        )
        for character in moved_back:
            character.series_id = child.id
            character.source_series_id = None
            character.danbooru_url = DanbooruClient.build_danbooru_url(
                character.character_tag,
                child.series_tag,
            )

        child.parent_series_id = None
        child.merged_moved_count = 0
        child.merged_duplicate_count = 0
        if child.status == "disabled":
            child.status = "collected"

        commit_db_session(self.db)
        child_character_count = self.db.query(Character.id).filter(Character.series_id == child.id).count()
        return UnmergeResult(
            child_series_id=child.id,
            child_series_tag=child.series_tag,
            moved_back_count=len(moved_back),
            child_character_count=child_character_count,
        )
