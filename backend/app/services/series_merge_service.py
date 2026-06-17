from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.danbooru.client import DanbooruClient
from app.models.character import Character
from app.models.series import Series
from app.services.collect_job_manager import series_job_manager

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


class SeriesMergeService:
    def __init__(self, db: Session):
        self.db = db

    def _get_series(self, series_id: int) -> Series | None:
        return self.db.query(Series).filter(Series.id == series_id).first()

    def _ensure_mergeable(self, series: Series, *, role: str) -> None:
        if series.status not in MERGEABLE_STATUSES:
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
    def _rank_candidates(anchor: Series, candidates: list[Series], *, search: str | None, limit: int) -> list[Series]:
        def sort_key(item: Series) -> tuple[float, int, float]:
            return (-item.post_count, -similarity_score(anchor, item), item.series_tag.lower())

        ranked = sorted(candidates, key=sort_key)
        if search:
            return ranked[:limit]
        similar = [item for item in ranked if similarity_score(anchor, item) > 0]
        return similar[:limit] if similar else ranked[:limit]

    def list_parent_candidates(
        self,
        child: Series,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[Series]:
        query = self.db.query(Series).filter(
            Series.id != child.id,
            Series.parent_series_id.is_(None),
            Series.status.in_(MERGEABLE_STATUSES),
        )
        if exclude_ids:
            query = query.filter(~Series.id.in_(exclude_ids))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                (Series.series_tag.ilike(pattern)) | (Series.display_name.ilike(pattern))
            )
        candidates = query.limit(max(limit * 4, 100)).all()
        return self._rank_candidates(child, candidates, search=search, limit=limit)

    def list_child_candidates(
        self,
        parent: Series,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[Series]:
        query = self.db.query(Series).filter(
            Series.id != parent.id,
            Series.parent_series_id.is_(None),
            Series.status.in_(MERGEABLE_STATUSES),
        )
        if exclude_ids:
            query = query.filter(~Series.id.in_(exclude_ids))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                (Series.series_tag.ilike(pattern)) | (Series.display_name.ilike(pattern))
            )
        candidates = query.limit(max(limit * 4, 100)).all()
        series_with_children = {
            row[0]
            for row in self.db.query(Series.parent_series_id)
            .filter(Series.parent_series_id.isnot(None))
            .distinct()
            .all()
            if row[0] is not None
        }
        filtered = [item for item in candidates if item.id not in series_with_children]
        return self._rank_candidates(parent, filtered, search=search, limit=limit)

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

        self.db.commit()
        self.db.refresh(parent)

        parent_character_count = (
            self.db.query(Character.id).filter(Character.series_id == parent.id).count()
        )
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

        self.db.commit()
        child_character_count = self.db.query(Character.id).filter(Character.series_id == child.id).count()
        return UnmergeResult(
            child_series_id=child.id,
            child_series_tag=child.series_tag,
            moved_back_count=len(moved_back),
            child_character_count=child_character_count,
        )
