from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import commit_db_session

_NAME_SIMILARITY_THRESHOLD = 0.5

_PAREN_RE = re.compile(r"\([^()]*\)")


def _normalize_tag(value: str) -> str:
    cleaned = re.sub(r"[()]", " ", value.lower())
    cleaned = re.sub(r"[_\-/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tag_tokens(value: str) -> set[str]:
    tokens = set(_normalize_tag(value).split())
    return {token for token in tokens if len(token) >= 2}


def _base_tag(character_tag: str) -> str:
    """괄호로 감싼 의상/변형 suffix를 제거한 기본 태그.
    예: murasaki_shion_(1st_costume) -> murasaki_shion"""
    stripped = _PAREN_RE.sub("", character_tag)
    stripped = re.sub(r"_+", "_", stripped)
    return stripped.strip("_ ").lower()


def _is_normalized_base_match(anchor_tag: str, candidate_tag: str) -> bool:
    """괄호 제거 후 기본 태그가 상대방의 실제 태그와 완전히 일치하는 경우에만 매치로
    취급한다. 상대방은 이미 DB에 존재하는 GlobalCharacter 행이므로 이 비교 자체가
    '기본 태그가 실제 다른 GlobalCharacter로 존재하는지' 확인을 겸한다. 이렇게 하면
    (genshin_impact) 같은 시리즈 구분 괄호가 우연히 같은 기본 토큰을 만들어내도
    실제로 그 기본 태그를 가진 캐릭터가 없으면 매치되지 않는다."""
    anchor_lower = anchor_tag.lower()
    candidate_lower = candidate_tag.lower()
    anchor_base = _base_tag(anchor_tag)
    candidate_base = _base_tag(candidate_tag)
    if anchor_base != anchor_lower and anchor_base == candidate_lower:
        return True
    if candidate_base != candidate_lower and candidate_base == anchor_lower:
        return True
    return False


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _name_similarity(left: str, right: str) -> float:
    left_norm = (left or "").strip().lower()
    right_norm = (right or "").strip().lower()
    if not left_norm or not right_norm:
        return 0.0
    return difflib.SequenceMatcher(None, left_norm, right_norm).ratio()


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


@dataclass
class RankedCandidate:
    character: GlobalCharacter
    match_reason: str


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

    def _series_id_map(self, character_ids: set[int]) -> dict[int, set[int]]:
        if not character_ids:
            return {}
        rows = (
            self.db.query(CharacterSeriesLink.global_character_id, CharacterSeriesLink.series_id)
            .filter(
                CharacterSeriesLink.global_character_id.in_(character_ids),
                CharacterSeriesLink.series_id.is_not(None),
            )
            .all()
        )
        result: dict[int, set[int]] = {}
        for character_id, series_id in rows:
            result.setdefault(character_id, set()).add(series_id)
        return result

    def _score(
        self,
        anchor: GlobalCharacter,
        candidate: GlobalCharacter,
        *,
        anchor_series_ids: set[int],
        series_map: dict[int, set[int]],
    ) -> tuple[tuple, str | None]:
        base_match = _is_normalized_base_match(anchor.character_tag, candidate.character_tag)
        same_series = bool(anchor_series_ids & series_map.get(candidate.id, set()))
        tag_sim = similarity_score(anchor, candidate)
        name_sim = _name_similarity(anchor.display_name, candidate.display_name)

        if base_match:
            reason: str | None = "base_tag_match"
        elif same_series:
            reason = "same_series"
        elif tag_sim > 0 or name_sim >= _NAME_SIMILARITY_THRESHOLD:
            reason = "name_similarity"
        else:
            reason = None

        sort_key = (
            0 if base_match else 1,
            0 if same_series else 1,
            -tag_sim,
            -name_sim,
            -candidate.post_count,
            candidate.character_tag.lower(),
        )
        return sort_key, reason

    def _rank_recommendations(
        self, anchor: GlobalCharacter, candidates: list[GlobalCharacter], *, limit: int
    ) -> list[RankedCandidate]:
        if not candidates:
            return []

        candidate_ids = {item.id for item in candidates}
        series_map = self._series_id_map(candidate_ids | {anchor.id})
        anchor_series_ids = series_map.get(anchor.id, set())

        scored: list[tuple[tuple, str, GlobalCharacter]] = []
        for candidate in candidates:
            sort_key, reason = self._score(
                anchor, candidate, anchor_series_ids=anchor_series_ids, series_map=series_map
            )
            if reason is None:
                # 안전장치: 유사도 신호가 전혀 없는 후보는 추천하지 않는다
                # (포스트 수 기준 fallback으로 무관한 인기 캐릭터가 추천되는 것을 방지).
                continue
            scored.append((sort_key, reason, candidate))

        scored.sort(key=lambda entry: entry[0])
        return [RankedCandidate(character=candidate, match_reason=reason) for _, reason, candidate in scored[:limit]]

    def _rank_search_results(
        self, anchor: GlobalCharacter, candidates: list[GlobalCharacter], *, limit: int
    ) -> list[RankedCandidate]:
        ranked = sorted(candidates, key=lambda item: (-item.post_count, item.character_tag.lower()))
        top = ranked[:limit]
        if not top:
            return []

        candidate_ids = {item.id for item in top}
        series_map = self._series_id_map(candidate_ids | {anchor.id})
        anchor_series_ids = series_map.get(anchor.id, set())

        results: list[RankedCandidate] = []
        for candidate in top:
            _, reason = self._score(
                anchor, candidate, anchor_series_ids=anchor_series_ids, series_map=series_map
            )
            results.append(RankedCandidate(character=candidate, match_reason=reason or ""))
        return results

    def _search_candidates(
        self, query, *, anchor: GlobalCharacter, search: str, limit: int
    ) -> list[RankedCandidate]:
        like = f"%{search.strip()}%"
        filtered = query.filter(
            or_(
                GlobalCharacter.character_tag.ilike(like),
                GlobalCharacter.display_name.ilike(like),
            )
        ).order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
        return self._rank_search_results(anchor, filtered.limit(limit).all(), limit=limit)

    def _find_normalized_injection_candidates(
        self, anchor: GlobalCharacter, *, exclude_ids: set[int] | None
    ) -> list[GlobalCharacter]:
        """기본 정렬 pool(post_count 상위)에 들어오지 못했더라도, 정규화된 기본 태그가
        일치하는 후보(부모 방향)나 anchor의 의상 변형 후보(자식 방향)는 별도로 찾아
        pool에 합류시킨다. 그렇지 않으면 인기 있는 무관한 캐릭터로 fallback되는
        문제가 재현된다."""
        found: dict[int, GlobalCharacter] = {}

        base = _base_tag(anchor.character_tag)
        if base and base != anchor.character_tag.lower():
            query = self.db.query(GlobalCharacter).filter(
                func.lower(GlobalCharacter.character_tag) == base,
                GlobalCharacter.id != anchor.id,
            )
            if exclude_ids:
                query = query.filter(~GlobalCharacter.id.in_(exclude_ids))
            for row in query.limit(10).all():
                found[row.id] = row

        prefix = _escape_like(anchor.character_tag) + "\\_("
        variant_query = self.db.query(GlobalCharacter).filter(
            GlobalCharacter.character_tag.ilike(f"{prefix}%", escape="\\"),
            GlobalCharacter.id != anchor.id,
        )
        if exclude_ids:
            variant_query = variant_query.filter(~GlobalCharacter.id.in_(exclude_ids))
        for row in variant_query.limit(20).all():
            found.setdefault(row.id, row)

        return list(found.values())

    def _list_candidates(
        self,
        anchor: GlobalCharacter,
        *,
        role: str,
        search: str | None,
        limit: int,
        exclude_ids: set[int] | None,
    ) -> list[RankedCandidate]:
        linkable_only = role == "child"
        query = self._base_candidate_query(anchor, exclude_ids=exclude_ids)
        if linkable_only:
            query = query.filter(GlobalCharacter.parent_character_id.is_(None))

        if search:
            return self._search_candidates(query, anchor=anchor, search=search, limit=limit)

        ordered = query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
        pool_size = max(limit * 8, 400)
        candidates = ordered.limit(pool_size).all()

        has_children_ids: set[int] = set()
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

        pool_ids = {item.id for item in candidates}
        exclude_for_injection = pool_ids | (exclude_ids or set()) | {anchor.id}
        injected = self._find_normalized_injection_candidates(anchor, exclude_ids=exclude_for_injection)
        if role == "child":
            injected = [
                item
                for item in injected
                if item.parent_character_id is None and item.id not in has_children_ids
            ]

        return self._rank_recommendations(anchor, candidates + injected, limit=limit)

    def list_parent_candidates(
        self,
        child: GlobalCharacter,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[RankedCandidate]:
        return self._list_candidates(child, role="parent", search=search, limit=limit, exclude_ids=exclude_ids)

    def list_child_candidates(
        self,
        parent: GlobalCharacter,
        *,
        search: str | None = None,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[RankedCandidate]:
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
