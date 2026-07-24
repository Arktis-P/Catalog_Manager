from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import commit_db_session

_STRONG_NAME_SIMILARITY_THRESHOLD = 0.76
_POST_COUNT_TIEBREAK_CAP = 1_000_000

_QUALIFIER_RE = re.compile(r"_\(([^()]*)\)")


def _normalize_tag(value: str) -> str:
    cleaned = re.sub(r"[()]", " ", value.lower())
    cleaned = re.sub(r"[_\-/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tag_tokens(value: str) -> set[str]:
    tokens = set(_normalize_tag(value).split())
    return {token for token in tokens if len(token) >= 2}


@dataclass(frozen=True)
class ParsedCharacterTag:
    base: str
    qualifiers: tuple[str, ...]


@dataclass(frozen=True)
class StructuralRelation:
    tier: int
    removed_count: int
    shared_count: int


@dataclass(frozen=True)
class CandidateScore:
    final_score: float
    base_similarity: float
    shared_qualifier_count: int
    same_series: bool
    relation_tier: int
    match_reason: str | None


def _parse_character_tag(value: str) -> ParsedCharacterTag:
    lowered = (value or "").strip().lower()
    if not lowered:
        return ParsedCharacterTag(base="", qualifiers=())

    qualifiers = tuple(match.group(1).strip().lower() for match in _QUALIFIER_RE.finditer(lowered))
    base = _QUALIFIER_RE.sub("", lowered)
    base = re.sub(r"_+", "_", base).strip("_ ")
    return ParsedCharacterTag(base=base or lowered, qualifiers=qualifiers)


def _is_ordered_subsequence(smaller: tuple[str, ...], larger: tuple[str, ...]) -> bool:
    if not smaller:
        return True
    cursor = 0
    for item in larger:
        if item == smaller[cursor]:
            cursor += 1
            if cursor == len(smaller):
                return True
    return False


def _structural_relation(
    anchor: ParsedCharacterTag,
    candidate: ParsedCharacterTag,
    *,
    role: str,
) -> StructuralRelation | None:
    if not anchor.base or anchor.base != candidate.base:
        return None

    if role == "parent":
        if len(candidate.qualifiers) >= len(anchor.qualifiers):
            return None
        if not _is_ordered_subsequence(candidate.qualifiers, anchor.qualifiers):
            return None
        removed_count = len(anchor.qualifiers) - len(candidate.qualifiers)
        return StructuralRelation(
            tier=0 if removed_count == 1 else 1,
            removed_count=removed_count,
            shared_count=len(candidate.qualifiers),
        )

    if len(candidate.qualifiers) <= len(anchor.qualifiers):
        return None
    if not _is_ordered_subsequence(anchor.qualifiers, candidate.qualifiers):
        return None
    removed_count = len(candidate.qualifiers) - len(anchor.qualifiers)
    return StructuralRelation(
        tier=0 if removed_count == 1 else 1,
        removed_count=removed_count,
        shared_count=len(anchor.qualifiers),
    )


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

    left_base = _parse_character_tag(left.character_tag).base
    right_base = _parse_character_tag(right.character_tag).base
    base_similarity = _name_similarity(left_base, right_base)
    if base_similarity >= _STRONG_NAME_SIMILARITY_THRESHOLD:
        return base_similarity

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
    similarity_score: float


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
        role: str,
        anchor_series_ids: set[int],
        series_map: dict[int, set[int]],
    ) -> tuple[tuple, CandidateScore | None]:
        anchor_parsed = _parse_character_tag(anchor.character_tag)
        candidate_parsed = _parse_character_tag(candidate.character_tag)
        relation = _structural_relation(anchor_parsed, candidate_parsed, role=role)
        same_base = anchor_parsed.base == candidate_parsed.base
        same_series = bool(anchor_series_ids & series_map.get(candidate.id, set()))
        base_sim = _name_similarity(anchor_parsed.base, candidate_parsed.base)
        name_sim = _name_similarity(anchor.display_name, candidate.display_name)

        if relation is not None:
            reason: str | None = "structural_parent" if role == "parent" else "structural_child"
            relation_tier = relation.tier
            removed_count = relation.removed_count
            shared_count = relation.shared_count
        elif same_base:
            reason = "same_base"
            relation_tier = 2
            removed_count = 999
            shared_count = len(set(anchor_parsed.qualifiers) & set(candidate_parsed.qualifiers))
        elif base_sim >= _STRONG_NAME_SIMILARITY_THRESHOLD or name_sim >= _STRONG_NAME_SIMILARITY_THRESHOLD:
            reason = "name_similarity"
            relation_tier = 3
            removed_count = 999
            shared_count = len(set(anchor_parsed.qualifiers) & set(candidate_parsed.qualifiers))
        else:
            return (), None

        sort_key = (
            relation_tier,
            removed_count,
            -shared_count,
            -base_sim,
            0 if same_series else 1,
            -min(candidate.post_count, _POST_COUNT_TIEBREAK_CAP),
            candidate.character_tag.lower(),
        )
        final_score = max(base_sim, name_sim)
        if relation is not None:
            final_score = max(final_score, 1.0 - (relation_tier * 0.1))
        return sort_key, CandidateScore(
            final_score=final_score,
            base_similarity=base_sim,
            shared_qualifier_count=shared_count,
            same_series=same_series,
            relation_tier=relation_tier,
            match_reason=reason,
        )

    def _rank_recommendations(
        self, anchor: GlobalCharacter, candidates: list[GlobalCharacter], *, role: str, limit: int
    ) -> list[RankedCandidate]:
        if not candidates:
            return []

        candidate_ids = {item.id for item in candidates}
        series_map = self._series_id_map(candidate_ids | {anchor.id})
        anchor_series_ids = series_map.get(anchor.id, set())

        scored: list[tuple[tuple, CandidateScore, GlobalCharacter]] = []
        for candidate in candidates:
            sort_key, score = self._score(
                anchor, candidate, role=role, anchor_series_ids=anchor_series_ids, series_map=series_map
            )
            if score is None:
                # 안전장치: 유사도 신호가 전혀 없는 후보는 추천하지 않는다
                # (포스트 수 기준 fallback으로 무관한 인기 캐릭터가 추천되는 것을 방지).
                continue
            linkable_rank = 0 if self.candidate_is_linkable(candidate, role=role) else 1
            scored.append(((linkable_rank, *sort_key), score, candidate))

        scored.sort(key=lambda entry: entry[0])
        return [
            RankedCandidate(
                character=candidate,
                match_reason=score.match_reason or "",
                similarity_score=score.final_score,
            )
            for _, score, candidate in scored[:limit]
        ]

    def _rank_search_results(
        self, anchor: GlobalCharacter, candidates: list[GlobalCharacter], *, role: str, search: str, limit: int
    ) -> list[RankedCandidate]:
        if not candidates:
            return []

        search_norm = search.strip().lower()
        candidate_ids = {item.id for item in candidates}
        series_map = self._series_id_map(candidate_ids | {anchor.id})
        anchor_series_ids = series_map.get(anchor.id, set())

        ranked: list[tuple[tuple, CandidateScore | None, GlobalCharacter]] = []
        for candidate in candidates:
            sort_key, score = self._score(
                anchor,
                candidate,
                role=role,
                anchor_series_ids=anchor_series_ids,
                series_map=series_map,
            )
            tag = candidate.character_tag.lower()
            display_name = (candidate.display_name or "").lower()
            if tag == search_norm:
                search_rank = 0
            elif tag.startswith(search_norm):
                search_rank = 1
            elif display_name == search_norm:
                search_rank = 2
            elif search_norm in tag or search_norm in display_name:
                search_rank = 3
            else:
                search_rank = 4
            if score is None:
                sort_key = (9, 999, 0, 0, 1, -min(candidate.post_count, _POST_COUNT_TIEBREAK_CAP), tag)
            ranked.append(((search_rank, *sort_key), score, candidate))

        ranked.sort(key=lambda item: item[0])
        results: list[RankedCandidate] = []
        for _, score, candidate in ranked[:limit]:
            results.append(
                RankedCandidate(
                    character=candidate,
                    match_reason=(score.match_reason if score else "") or "",
                    similarity_score=score.final_score if score else 0.0,
                )
            )
        return results

    def _search_candidates(
        self, query, *, anchor: GlobalCharacter, role: str, search: str, limit: int
    ) -> list[RankedCandidate]:
        like = f"%{search.strip()}%"
        filtered = query.filter(
            or_(
                GlobalCharacter.character_tag.ilike(like),
                GlobalCharacter.display_name.ilike(like),
            )
        ).order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc())
        pool_size = max(limit * 8, 200)
        candidates = {item.id: item for item in filtered.limit(pool_size).all()}

        search_value = search.strip().lower()
        prefix = f"{_escape_like(search_value)}%"
        priority_matches = query.filter(
            or_(
                GlobalCharacter.character_tag == search_value,
                GlobalCharacter.character_tag.like(prefix, escape="\\"),
                GlobalCharacter.display_name.ilike(search.strip()),
            )
        ).limit(100)
        for item in priority_matches.all():
            candidates[item.id] = item

        return self._rank_search_results(anchor, list(candidates.values()), role=role, search=search, limit=limit)

    def _find_same_base_candidates(
        self,
        anchor: GlobalCharacter,
        *,
        exclude_ids: set[int] | None,
        limit: int = 200,
    ) -> list[GlobalCharacter]:
        """기본 정렬 pool(post_count 상위)에 들어오지 못했더라도, 정규화된 기본 태그가
        일치하는 후보(부모 방향)나 anchor의 의상 변형 후보(자식 방향)는 별도로 찾아
        pool에 합류시킨다. 그렇지 않으면 인기 있는 무관한 캐릭터로 fallback되는
        문제가 재현된다."""
        found: dict[int, GlobalCharacter] = {}

        base = _parse_character_tag(anchor.character_tag).base
        if not base:
            return []

        escaped_base = _escape_like(base)
        query = self.db.query(GlobalCharacter).filter(
            or_(
                GlobalCharacter.character_tag == base,
                GlobalCharacter.character_tag.like(f"{escaped_base}\\_(%", escape="\\"),
            ),
            GlobalCharacter.id != anchor.id,
        )
        if exclude_ids:
            query = query.filter(~GlobalCharacter.id.in_(exclude_ids))
        for row in query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc()).limit(limit).all():
            found[row.id] = row

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
            return self._search_candidates(query, anchor=anchor, role=role, search=search, limit=limit)

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
        injected = self._find_same_base_candidates(anchor, exclude_ids=exclude_for_injection)
        if role == "child":
            injected = [
                item
                for item in injected
                if item.parent_character_id is None and item.id not in has_children_ids
            ]

        return self._rank_recommendations(anchor, candidates + injected, role=role, limit=limit)

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
