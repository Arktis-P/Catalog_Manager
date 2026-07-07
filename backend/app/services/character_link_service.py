from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import commit_db_session


def _normalize_tag(value: str) -> str:
    cleaned = re.sub(r"[()]", " ", value.lower())
    cleaned = re.sub(r"[_\-/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tag_tokens(value: str) -> set[str]:
    tokens = set(_normalize_tag(value).split())
    return {token for token in tokens if len(token) >= 2}


def similarity_score(left: GlobalCharacter, right: GlobalCharacter) -> float:
    """의상 차이로 이름이 갈라진 동일 캐릭터를 찾기 위한 토큰 중복 기반 유사도.
    series_merge_service.similarity_score와 동일한 방식을 캐릭터 태그에 적용한다."""
    if left.id == right.id:
        return -1.0

    left_tag = left.character_tag.lower()
    right_tag = right.character_tag.lower()
    if left_tag in right_tag or right_tag in left_tag:
        return 0.95

    left_tokens = _tag_tokens(left.character_tag) | _tag_tokens(left.display_name or "")
    right_tokens = _tag_tokens(right.character_tag) | _tag_tokens(right.display_name or "")
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(len(left_tokens), len(right_tokens))


@dataclass
class LinkResult:
    child_id: int
    child_character_tag: str
    parent_id: int
    parent_character_tag: str


class CharacterLinkService:
    def __init__(self, db: Session):
        self.db = db

    def _get(self, character_id: int) -> GlobalCharacter | None:
        return self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()

    def _child_count(self, character_id: int) -> int:
        return (
            self.db.query(GlobalCharacter.id)
            .filter(GlobalCharacter.parent_character_id == character_id)
            .count()
        )

    def _ensure_parent_candidate(self, character: GlobalCharacter) -> None:
        if character.parent_character_id is not None:
            raise ValueError("Parent character cannot already be linked under another character.")

    def _ensure_child_candidate(self, character: GlobalCharacter) -> None:
        if character.parent_character_id is not None:
            raise ValueError("Character is already linked to a parent character.")
        if self._child_count(character.id) > 0:
            raise ValueError("Character with its own children cannot be linked under another parent.")

    def candidate_is_linkable(self, character: GlobalCharacter, *, role: str) -> bool:
        if role == "parent":
            return character.parent_character_id is None
        return character.parent_character_id is None and self._child_count(character.id) == 0

    def _base_candidate_query(self, anchor: GlobalCharacter, *, exclude_ids: set[int] | None):
        query = self.db.query(GlobalCharacter).filter(GlobalCharacter.id != anchor.id)
        if exclude_ids:
            query = query.filter(~GlobalCharacter.id.in_(exclude_ids))
        return query

    def _rank_recommendations(
        self, anchor: GlobalCharacter, candidates: list[GlobalCharacter], *, limit: int
    ) -> list[GlobalCharacter]:
        def sort_key(item: GlobalCharacter) -> tuple[float, int, str]:
            return (-similarity_score(anchor, item), -item.post_count, item.character_tag.lower())

        ranked = sorted(candidates, key=sort_key)
        similar = [item for item in ranked if similarity_score(anchor, item) > 0]
        return similar[:limit] if similar else ranked[:limit]

    def _rank_search_results(self, candidates: list[GlobalCharacter], *, limit: int) -> list[GlobalCharacter]:
        ranked = sorted(candidates, key=lambda item: (-item.post_count, item.character_tag.lower()))
        return ranked[:limit]

    def _search_candidates(self, query, *, search: str, limit: int) -> list[GlobalCharacter]:
        like = f"%{search.strip()}%"
        filtered = query.filter(
            or_(
                GlobalCharacter.character_tag.ilike(like),
                GlobalCharacter.display_name.ilike(like),
            )
        ).order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
        return self._rank_search_results(filtered.limit(limit).all(), limit=limit)

    def _list_candidates(
        self,
        anchor: GlobalCharacter,
        *,
        role: str,
        search: str | None,
        limit: int,
        exclude_ids: set[int] | None,
    ) -> list[GlobalCharacter]:
        linkable_only = role == "child"
        query = self._base_candidate_query(anchor, exclude_ids=exclude_ids)
        if linkable_only:
            query = query.filter(GlobalCharacter.parent_character_id.is_(None))

        if search:
            return self._search_candidates(query, search=search, limit=limit)

        ordered = query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
        pool_size = max(limit * 8, 400)
        candidates = ordered.limit(pool_size).all()

        if role == "child":
            has_children_ids = {
                row[0]
                for row in self.db.query(GlobalCharacter.parent_character_id)
                .filter(GlobalCharacter.parent_character_id.isnot(None))
                .distinct()
                .all()
                if row[0] is not None
            }
            candidates = [item for item in candidates if item.id not in has_children_ids]

        return self._rank_recommendations(anchor, candidates, limit=limit)

    def list_parent_candidates(
        self,
        child: GlobalCharacter,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[GlobalCharacter]:
        return self._list_candidates(child, role="parent", search=search, limit=limit, exclude_ids=exclude_ids)

    def list_child_candidates(
        self,
        parent: GlobalCharacter,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[GlobalCharacter]:
        return self._list_candidates(parent, role="child", search=search, limit=limit, exclude_ids=exclude_ids)

    def link_parent(self, child_id: int, parent_id: int) -> LinkResult:
        if child_id == parent_id:
            raise ValueError("Cannot link a character to itself.")
        child = self._get(child_id)
        parent = self._get(parent_id)
        if not child or not parent:
            raise ValueError("Character not found.")

        self._ensure_child_candidate(child)
        self._ensure_parent_candidate(parent)

        child.parent_character_id = parent.id
        commit_db_session(self.db)
        self.db.refresh(child)
        return LinkResult(
            child_id=child.id,
            child_character_tag=child.character_tag,
            parent_id=parent.id,
            parent_character_tag=parent.character_tag,
        )

    def unlink_parent(self, child_id: int) -> LinkResult:
        child = self._get(child_id)
        if not child:
            raise ValueError("Character not found.")
        if child.parent_character_id is None:
            raise ValueError("Character is not linked to a parent character.")

        parent = self._get(child.parent_character_id)
        parent_id = child.parent_character_id
        parent_tag = parent.character_tag if parent else ""
        child.parent_character_id = None
        commit_db_session(self.db)
        self.db.refresh(child)
        return LinkResult(
            child_id=child.id,
            child_character_tag=child.character_tag,
            parent_id=parent_id,
            parent_character_tag=parent_tag,
        )
