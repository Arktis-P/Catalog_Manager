from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from sqlalchemy import and_, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.danbooru.client import DanbooruClient
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.parent_child_candidate_dismissal import ParentChildCandidateDismissal
from app.services.character_link_service import (
    CharacterLinkService,
    _name_similarity,
    _parse_character_tag,
    _structural_relation,
)
from app.services.db_write_queue import commit_db_session

NON_HUMAN_CLASSIFIER_VERSION = "non_human_rules_v1"
_REFERENCE_CACHE_TTL_SECONDS = 30 * 60
_REFERENCE_CACHE_MAX_ENTRIES = 100
_REFERENCE_CACHE: OrderedDict[tuple[int, int], tuple[float, dict[str, Any]]] = OrderedDict()

_NON_HUMAN_SERIES_TERMS = {
    "pokemon",
    "digimon",
    "monster",
    "monster_hunter",
    "my_little_pony",
    "sonic_the_hedgehog",
}
_NON_HUMAN_TAG_TERMS = {
    "pokemon_(creature)",
    "digimon_(creature)",
    "animal",
    "monster",
    "creature",
    "mascot",
    "non-human",
    "non_human",
    "no_humans",
    "quadruped",
    "feral",
    "bird",
    "canine",
    "feline",
    "robot",
    "mecha",
    "object",
    "slime",
    "dragon",
}


@dataclass(frozen=True)
class PipelineImage:
    id: int
    image_path: str
    is_cover: bool
    is_rejected: bool
    auto_status: str | None
    quality_status: str | None
    identity_status: str | None
    cover_score: float | None


@dataclass(frozen=True)
class ParentChildCandidate:
    character: GlobalCharacter
    reasons: list[str]
    confidence: float
    default_selected: bool
    already_linked: bool


@dataclass(frozen=True)
class ParentChildGroup:
    group_id: str
    parent: ParentChildCandidate
    children: list[ParentChildCandidate]
    conflict_count: int
    reasons: list[str]


@dataclass(frozen=True)
class ParentChildApplyResult:
    parent_id: int
    linked_child_ids: list[int]
    unlinked_child_ids: list[int]
    inherited_fields: dict[int, list[str]]
    conflicts: list[dict[str, Any]]
    completed_child_ids: list[int]
    parent_completed: bool


@dataclass(frozen=True)
class NonHumanCandidate:
    character: GlobalCharacter
    score: float
    reasons: list[str]
    related_tags: list[str]


class ReviewPipelineService:
    def __init__(self, db: Session):
        self.db = db
        self.link_service = CharacterLinkService(db)

    @staticmethod
    def preview_image(character: GlobalCharacter) -> PipelineImage | None:
        visible = [image for image in character.images if not image.is_rejected]
        if not visible:
            return None
        image = sorted(visible, key=lambda item: (not item.is_cover, -(item.cover_score or 0), item.id))[0]
        return PipelineImage(
            id=image.id,
            image_path=image.image_path,
            is_cover=image.is_cover,
            is_rejected=image.is_rejected,
            auto_status=image.auto_status,
            quality_status=image.quality_status,
            identity_status=image.identity_status,
            cover_score=image.cover_score,
        )

    def _base_character_query(self):
        return self.db.query(GlobalCharacter).options(
            joinedload(GlobalCharacter.images),
            joinedload(GlobalCharacter.review),
            joinedload(GlobalCharacter.parent),
            selectinload(GlobalCharacter.children),
            selectinload(GlobalCharacter.series_links).joinedload(CharacterSeriesLink.series),
            selectinload(GlobalCharacter.appearance_relevances),
        )

    def _load_character(self, character_id: int) -> GlobalCharacter | None:
        return self._base_character_query().filter(GlobalCharacter.id == character_id).first()

    def _dismissed_candidate_ids(self, parent_id: int) -> set[int]:
        return {
            row[0]
            for row in self.db.query(ParentChildCandidateDismissal.candidate_character_id)
            .filter(ParentChildCandidateDismissal.parent_character_id == parent_id)
            .all()
        }

    def _group_search_query(self, *, series_id: int | None, search: str | None):
        query = self.db.query(GlobalCharacter)
        if series_id is not None:
            query = query.join(CharacterSeriesLink, CharacterSeriesLink.global_character_id == GlobalCharacter.id)
            query = query.filter(CharacterSeriesLink.series_id == series_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(GlobalCharacter.character_tag.ilike(pattern), GlobalCharacter.display_name.ilike(pattern))
            )
        return query.distinct()

    def list_parent_child_groups(
        self,
        *,
        series_id: int | None = None,
        search: str | None = None,
        confidence: str = "all",
        already_linked_only: bool = False,
        unreviewed_first: bool = False,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[list[ParentChildGroup], int]:
        query = self._eligible_parent_query(
            series_id=series_id,
            search=search,
            confidence=confidence,
            already_linked_only=already_linked_only,
        )

        ordering = [GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc()]
        if unreviewed_first:
            query = query.outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            ordering.insert(0, func.coalesce(GlobalCharacterReview.review_status, "pending").asc())
        total = query.distinct().order_by(None).count()
        parent_ids = [
            row[0]
            for row in query.with_entities(GlobalCharacter.id)
            .distinct()
            .order_by(*ordering)
            .offset(skip)
            .limit(limit)
            .all()
        ]
        groups: list[ParentChildGroup] = []
        for parent_id in parent_ids:
            group = self.get_parent_child_group(parent_id, confidence=confidence)
            if group.children:
                groups.append(group)
        return groups, total

    def _eligible_parent_query(
        self,
        *,
        series_id: int | None,
        search: str | None,
        confidence: str,
        already_linked_only: bool,
    ):
        query = self._group_search_query(series_id=series_id, search=search).filter(
            GlobalCharacter.parent_character_id.is_(None)
        )
        linked_child = aliased(GlobalCharacter)
        linked_exists = exists(
            select(1).where(
                linked_child.parent_character_id == GlobalCharacter.id,
                ~exists(
                    select(1).where(
                        ParentChildCandidateDismissal.parent_character_id == GlobalCharacter.id,
                        ParentChildCandidateDismissal.candidate_character_id == linked_child.id,
                    )
                ),
            )
        )
        if already_linked_only:
            return query.filter(linked_exists)

        structural_child = aliased(GlobalCharacter)
        parent_base = func.substr(
            GlobalCharacter.character_tag,
            1,
            func.coalesce(func.nullif(func.instr(GlobalCharacter.character_tag, "_("), 0), func.length(GlobalCharacter.character_tag) + 1)
            - 1,
        )
        child_base = func.substr(
            structural_child.character_tag,
            1,
            func.coalesce(func.nullif(func.instr(structural_child.character_tag, "_("), 0), func.length(structural_child.character_tag) + 1)
            - 1,
        )
        parent_qualifier_count = (
            (func.length(GlobalCharacter.character_tag) - func.length(func.replace(GlobalCharacter.character_tag, "_(", ""))) / 2
        )
        child_qualifier_count = (
            (func.length(structural_child.character_tag) - func.length(func.replace(structural_child.character_tag, "_(", ""))) / 2
        )
        structural_exists = exists(
            select(1).where(
                structural_child.id != GlobalCharacter.id,
                structural_child.parent_character_id.is_(None),
                child_base == parent_base,
                child_qualifier_count > parent_qualifier_count,
                structural_child.character_tag.like(parent_base + literal("\\_(%"), escape="\\"),
                ~exists(
                    select(1).where(
                        ParentChildCandidateDismissal.parent_character_id == GlobalCharacter.id,
                        ParentChildCandidateDismissal.candidate_character_id == structural_child.id,
                    )
                ),
                ~exists(
                    select(1).where(GlobalCharacter.parent_character_id == structural_child.id)
                ),
            )
        )
        return query.filter(or_(linked_exists, structural_exists))

    def get_parent_child_group(self, parent_id: int, *, confidence: str = "all") -> ParentChildGroup:
        parent = self._load_character(parent_id)
        if not parent:
            raise ValueError("Parent character not found")
        if parent.parent_character_id is not None:
            raise ValueError("Group parent cannot already be linked under another character")

        dismissed_ids = self._dismissed_candidate_ids(parent.id)
        existing_children = [child for child in parent.children if child.id not in dismissed_ids]
        exclude_ids = {child.id for child in existing_children} | dismissed_ids
        ranked = self.link_service.list_child_candidates(parent, limit=75, exclude_ids=exclude_ids)
        candidates: list[ParentChildCandidate] = [
            self._parent_child_candidate(parent, child, already_linked=True, forced_reason="already_linked")
            for child in existing_children
        ]
        for ranked_item in ranked:
            candidate = self._parent_child_candidate(
                parent,
                ranked_item.character,
                already_linked=False,
                forced_reason=ranked_item.match_reason,
                forced_score=ranked_item.similarity_score,
            )
            if confidence == "high" and candidate.confidence < 0.85:
                continue
            if confidence == "medium" and candidate.confidence < 0.7:
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda item: (not item.already_linked, not item.default_selected, -item.confidence, -item.character.post_count))
        parent_candidate = ParentChildCandidate(
            character=parent,
            reasons=["parent_candidate"],
            confidence=1.0,
            default_selected=True,
            already_linked=False,
        )
        return ParentChildGroup(
            group_id=str(parent.id),
            parent=parent_candidate,
            children=candidates,
            conflict_count=self._group_conflict_count(parent, [item.character for item in candidates]),
            reasons=self._group_reasons(parent, candidates),
        )

    def _parent_child_candidate(
        self,
        parent: GlobalCharacter,
        child: GlobalCharacter,
        *,
        already_linked: bool,
        forced_reason: str | None = None,
        forced_score: float | None = None,
    ) -> ParentChildCandidate:
        parent_parsed = _parse_character_tag(parent.character_tag)
        child_parsed = _parse_character_tag(child.character_tag)
        relation = _structural_relation(parent_parsed, child_parsed, role="child")
        reasons: list[str] = []
        if already_linked:
            reasons.append("already_linked")
        if relation:
            reasons.append("structural_child")
        if parent_parsed.base and parent_parsed.base == child_parsed.base:
            reasons.append("same_base")
        if forced_reason and forced_reason not in reasons:
            reasons.append(forced_reason)
        series_overlap = {link.series_id for link in parent.series_links} & {link.series_id for link in child.series_links}
        if series_overlap:
            reasons.append("same_series")
        if not reasons:
            reasons.append("name_similarity")
        confidence = forced_score if forced_score is not None else _name_similarity(parent_parsed.base, child_parsed.base)
        if relation:
            confidence = max(confidence, 0.92 if relation.tier == 0 else 0.84)
        if already_linked:
            confidence = max(confidence, 1.0)
        default_selected = already_linked or "structural_child" in reasons or confidence >= 0.85
        return ParentChildCandidate(
            character=child,
            reasons=list(dict.fromkeys(reasons)),
            confidence=round(confidence, 4),
            default_selected=default_selected,
            already_linked=already_linked,
        )

    @staticmethod
    def _group_reasons(parent: GlobalCharacter, candidates: list[ParentChildCandidate]) -> list[str]:
        reasons = {"parent_first"}
        if any(item.already_linked for item in candidates):
            reasons.add("has_existing_links")
        if any("structural_child" in item.reasons for item in candidates):
            reasons.add("structural_candidates")
        if parent.review and parent.review.review_status == "completed":
            reasons.add("parent_review_completed")
        return sorted(reasons)

    @staticmethod
    def _group_conflict_count(parent: GlobalCharacter, children: list[GlobalCharacter]) -> int:
        fields = ("gender", "primary_hair_color", "hair_color", "hair_shape", "eye_color")
        count = 0
        for child in children:
            for field in fields:
                parent_value = getattr(parent, field, None)
                child_value = getattr(child, field, None)
                if parent_value and child_value and parent_value != child_value:
                    count += 1
        return count

    def apply_parent_child_group(self, parent_id: int, payload) -> ParentChildApplyResult:
        parent = self._load_character(parent_id)
        if not parent:
            raise ValueError("Parent character not found")
        if parent.parent_character_id is not None:
            raise ValueError("Parent character cannot be linked under another parent")

        selected_ids = list(dict.fromkeys(payload.selected_child_ids))
        unlink_ids = list(dict.fromkeys(payload.unlink_child_ids))
        if parent.id in selected_ids or parent.id in unlink_ids:
            raise ValueError("Parent cannot be selected as a child")
        group = self.get_parent_child_group(parent.id, confidence="all")
        group_candidate_ids = {candidate.character.id for candidate in group.children}
        invalid_selected = sorted(set(selected_ids) - group_candidate_ids)
        if invalid_selected:
            raise ValueError(f"Selected character is not a candidate in this group: {invalid_selected[0]}")
        current_child_ids = {child.id for child in parent.children}
        invalid_unlink = sorted(set(unlink_ids) - current_child_ids)
        if invalid_unlink:
            raise ValueError(f"Unlink character is not currently linked to this parent: {invalid_unlink[0]}")
        target_ids = set(selected_ids) | set(unlink_ids)
        children = (
            self._base_character_query()
            .filter(GlobalCharacter.id.in_(target_ids))
            .all()
            if target_ids
            else []
        )
        by_id = {child.id: child for child in children}
        missing = sorted(target_ids - set(by_id))
        if missing:
            raise ValueError(f"Character not found: {missing[0]}")

        linked: list[int] = []
        unlinked: list[int] = []
        inherited: dict[int, list[str]] = {}
        conflicts: list[dict[str, Any]] = []
        completed_children: list[int] = []
        try:
            for child_id in selected_ids:
                child = by_id[child_id]
                if child.parent_character_id not in (None, parent.id):
                    raise ValueError(f"Child {child.id} is already linked to another parent")
                if child.children:
                    raise ValueError(f"Child {child.id} has children and cannot be linked under this parent")
                child.parent_character_id = parent.id
                linked.append(child.id)
                if payload.inherit_tags:
                    inherited_fields, field_conflicts = self._inherit_empty_parent_tags(parent, child)
                    if inherited_fields:
                        inherited[child.id] = inherited_fields
                    conflicts.extend(field_conflicts)
                review = self._ensure_review(child)
                if payload.apply_parent_rating and parent.review and parent.review.rating is not None:
                    review.rating = parent.review.rating
                if payload.complete_children:
                    review.review_status = (
                        "completed" if child.images or review.rating in (0, -1) else "inherited_review_pending_image"
                    )
                    if review.review_status == "completed":
                        completed_children.append(child.id)

            for child_id in unlink_ids:
                child = by_id[child_id]
                if child.parent_character_id == parent.id:
                    child.parent_character_id = None
                    unlinked.append(child.id)

            parent_completed = False
            if payload.complete_parent:
                parent_review = self._ensure_review(parent)
                parent_review.review_status = "completed"
                parent_completed = True

            commit_db_session(self.db)
        except Exception:
            self.db.rollback()
            raise
        return ParentChildApplyResult(
            parent_id=parent.id,
            linked_child_ids=linked,
            unlinked_child_ids=unlinked,
            inherited_fields=inherited,
            conflicts=conflicts,
            completed_child_ids=completed_children,
            parent_completed=parent_completed,
        )

    @staticmethod
    def _inherit_empty_parent_tags(parent: GlobalCharacter, child: GlobalCharacter) -> tuple[list[str], list[dict[str, Any]]]:
        inherited: list[str] = []
        conflicts: list[dict[str, Any]] = []
        for field in ("gender", "primary_hair_color", "hair_color", "hair_shape", "eye_color"):
            parent_value = normalize_gender(getattr(parent, field)) if field == "gender" and getattr(parent, field) else getattr(parent, field)
            child_value = normalize_gender(getattr(child, field)) if field == "gender" and getattr(child, field) else getattr(child, field)
            if parent_value and not child_value:
                setattr(child, field, parent_value)
                inherited.append(field)
            elif parent_value and child_value and parent_value != child_value:
                conflicts.append(
                    {
                        "child_id": child.id,
                        "field": field,
                        "parent_value": parent_value,
                        "child_value": child_value,
                    }
                )
        return inherited, conflicts

    def dismiss_parent_child_candidate(self, parent_id: int, candidate_id: int, reason: str | None = None) -> bool:
        if parent_id == candidate_id:
            raise ValueError("Parent candidate cannot be dismissed through this endpoint")
        parent = self._load_character(parent_id)
        if not parent:
            raise ValueError("Parent character not found")
        candidate = self._load_character(candidate_id)
        if not candidate:
            raise ValueError("Candidate character not found")
        if candidate.parent_character_id == parent.id:
            candidate.parent_character_id = None
            commit_db_session(self.db)
            return True
        group = self.get_parent_child_group(parent.id, confidence="all")
        if candidate_id not in {item.character.id for item in group.children}:
            raise ValueError("Candidate is not in this parent-child group")
        existing = (
            self.db.query(ParentChildCandidateDismissal)
            .filter(
                ParentChildCandidateDismissal.parent_character_id == parent.id,
                ParentChildCandidateDismissal.candidate_character_id == candidate.id,
            )
            .first()
        )
        if existing:
            existing.reason = reason
        else:
            self.db.add(
                ParentChildCandidateDismissal(
                    parent_character_id=parent.id,
                    candidate_character_id=candidate.id,
                    reason=reason,
                )
            )
        commit_db_session(self.db)
        return False

    def get_danbooru_reference_images(self, character_id: int, *, limit: int = 3) -> dict[str, Any]:
        limit = max(1, min(limit, 3))
        character = self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
        if not character:
            raise ValueError("Character not found")
        cache_key = (character.id, limit)
        cached = _REFERENCE_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < _REFERENCE_CACHE_TTL_SECONDS:
            _REFERENCE_CACHE.move_to_end(cache_key)
            return cached[1]

        result: dict[str, Any] = {
            "character_id": character.id,
            "character_tag": character.character_tag,
            "images": [],
            "source": "recent_posts",
            "error": None,
        }
        try:
            client = DanbooruClient()
            posts = client.list_posts(tags=f"{character.character_tag} order:rank", limit=min(20, max(limit * 4, 8)))
            images = []
            for post in posts:
                if post.get("is_deleted") or not (post.get("preview_file_url") or post.get("large_file_url") or post.get("file_url")):
                    continue
                post_id = int(post.get("id"))
                images.append(
                    {
                        "post_id": post_id,
                        "preview_url": post.get("preview_file_url"),
                        "sample_url": post.get("large_file_url"),
                        "file_url": post.get("file_url"),
                        "width": post.get("image_width"),
                        "height": post.get("image_height"),
                        "rating": post.get("rating"),
                        "post_url": f"{settings.danbooru_base_url}/posts/{post_id}",
                    }
                )
                if len(images) >= limit:
                    break
            result["images"] = images
        except Exception:
            result["error"] = "Danbooru reference lookup failed"

        _REFERENCE_CACHE[cache_key] = (now, result)
        _REFERENCE_CACHE.move_to_end(cache_key)
        while len(_REFERENCE_CACHE) > _REFERENCE_CACHE_MAX_ENTRIES:
            _REFERENCE_CACHE.popitem(last=False)
        return result

    def list_non_human_candidates(
        self,
        *,
        review_filter: str = "unreviewed",
        category: str | None = None,
        series_id: int | None = None,
        search: str | None = None,
        include_completed: bool = False,
        skip: int = 0,
        limit: int = 30,
    ) -> tuple[list[NonHumanCandidate], int]:
        query = (
            self._base_character_query()
            .outerjoin(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacter.id)
            .filter(self._non_human_sql_signal(category=category))
        )
        if series_id is not None:
            query = query.join(CharacterSeriesLink, CharacterSeriesLink.global_character_id == GlobalCharacter.id)
            query = query.filter(CharacterSeriesLink.series_id == series_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(GlobalCharacter.character_tag.ilike(pattern), GlobalCharacter.display_name.ilike(pattern))
            )
        if not include_completed:
            query = query.filter(
                or_(GlobalCharacterReview.id.is_(None), GlobalCharacterReview.review_status != "completed")
            )
        if review_filter == "unreviewed":
            query = query.filter(
                or_(
                    GlobalCharacterReview.id.is_(None),
                    GlobalCharacterReview.non_human_review_result.is_(None),
                )
            )
        elif review_filter == "reviewed":
            query = query.filter(GlobalCharacterReview.non_human_review_result.is_not(None))
        elif review_filter == "general_review":
            query = query.filter(GlobalCharacterReview.non_human_review_result == "general_review")

        total = query.distinct().order_by(None).count()
        rows = (
            query.distinct()
            .order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        candidates = [self._score_non_human_candidate(character) for character in rows]
        candidates.sort(key=lambda item: (-item.score, -item.character.post_count, item.character.character_tag))
        return candidates, total

    @staticmethod
    def _non_human_sql_signal(category: str | None = None):
        tag_patterns = [f"%{term.replace('-', '_')}%" for term in _NON_HUMAN_TAG_TERMS]
        series_patterns = [f"%{term}%" for term in _NON_HUMAN_SERIES_TERMS]
        tag_signal = or_(
            *[GlobalCharacter.character_tag.ilike(pattern) for pattern in tag_patterns],
            exists(
                select(1).where(
                    CharacterAppearanceTagRelevance.global_character_id == GlobalCharacter.id,
                    or_(*[CharacterAppearanceTagRelevance.tag.ilike(pattern) for pattern in tag_patterns]),
                )
            ),
        )
        tagger_signal = exists(
            select(1).where(
                GlobalCharacterImage.global_character_id == GlobalCharacter.id,
                or_(
                    *[GlobalCharacterImage.auto_tags.ilike(pattern) for pattern in tag_patterns],
                    *[GlobalCharacterImage.identity_reasons.ilike(pattern) for pattern in tag_patterns],
                ),
            )
        )
        series_signal = exists(
            select(1)
            .where(CharacterSeriesLink.global_character_id == GlobalCharacter.id)
            .where(or_(*[CharacterSeriesLink.copyright_tag.ilike(pattern) for pattern in series_patterns]))
        )
        gender_signal = or_(GlobalCharacter.gender.is_(None), GlobalCharacter.gender == "", GlobalCharacter.gender == "other")
        if category == "series":
            return series_signal
        if category == "tag":
            return tag_signal
        if category == "tagger":
            return tagger_signal
        if category == "gender":
            return and_(or_(tag_signal, tagger_signal, series_signal), gender_signal)
        return or_(
            tag_signal,
            tagger_signal,
            series_signal,
        )

    def _score_non_human_candidate(self, character: GlobalCharacter) -> NonHumanCandidate:
        reasons: list[str] = []
        score = 0.0
        series_tags = [link.copyright_tag for link in character.series_links]
        for series_tag in series_tags:
            if any(term in series_tag.lower() for term in _NON_HUMAN_SERIES_TERMS):
                score += 0.22
                reasons.append(f"series:{series_tag}")

        related_tags: list[str] = []
        for relevance in character.appearance_relevances:
            tag = relevance.tag.lower()
            related_tags.append(relevance.tag)
            if tag in _NON_HUMAN_TAG_TERMS or any(term in tag for term in _NON_HUMAN_TAG_TERMS):
                score += 0.28
                reasons.append(f"tag:{relevance.tag}")

        character_tag = character.character_tag.lower()
        if any(term in character_tag for term in _NON_HUMAN_TAG_TERMS):
            score += 0.2
            reasons.append("tag:character_tag")

        for image in character.images:
            text = " ".join(filter(None, [image.auto_tags, image.identity_reasons])).lower()
            for term in _NON_HUMAN_TAG_TERMS:
                if term.replace("-", "_") in text:
                    score += 0.25
                    reasons.append(f"tagger:{term}")
                    break

        normalized_gender = normalize_gender(character.review.gender if character.review and character.review.gender else character.gender)
        if normalized_gender in (None, "", "other"):
            score += 0.08
            reasons.append(f"gender:{normalized_gender or 'unknown'}")
        elif normalized_gender in ("1girl", "girl", "female"):
            score -= 0.1
            reasons.append("gender:female_signal")

        score = max(0.0, min(score, 1.0))
        if not reasons:
            reasons.append("candidate:weak_signal")
        return NonHumanCandidate(
            character=character,
            score=round(score, 4),
            reasons=list(dict.fromkeys(reasons)),
            related_tags=related_tags[:20],
        )

    def apply_non_human_decision(
        self,
        character_id: int,
        *,
        result: str,
        complete_review: bool = True,
        overwrite_existing: bool = False,
        reopen_completed: bool = False,
    ) -> GlobalCharacter:
        if result not in {"non_human", "generation_unavailable", "human_female", "general_review"}:
            raise ValueError("Invalid non-human review result")
        character = self._load_character(character_id)
        if not character:
            raise ValueError("Character not found")
        review = self._ensure_review(character)
        if review.review_status == "completed" and not reopen_completed:
            raise ValueError("Completed review requires reopen_completed=true")
        if review.rating is not None and not overwrite_existing:
            raise ValueError("Existing rating requires overwrite_existing=true")
        if review.non_human_review_result and not overwrite_existing:
            raise ValueError("Existing non-human decision requires overwrite_existing=true")
        candidate = self._score_non_human_candidate(character)
        review.non_human_candidate_score = candidate.score
        review.non_human_candidate_reasons = json.dumps(candidate.reasons, ensure_ascii=False)
        review.non_human_classifier_version = NON_HUMAN_CLASSIFIER_VERSION
        review.non_human_review_result = result
        review.non_human_reviewed_at = datetime.now(timezone.utc)
        if result == "general_review":
            review.review_status = "pending"
        else:
            rating_map = {
                "non_human": -1,
                "generation_unavailable": 0,
                "human_female": 3,
            }
            review.rating = rating_map[result]
            if complete_review:
                review.review_status = "completed"
        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def _ensure_review(self, character: GlobalCharacter) -> GlobalCharacterReview:
        if character.review:
            return character.review
        review = GlobalCharacterReview(global_character_id=character.id)
        self.db.add(review)
        character.review = review
        return review


def build_danbooru_wiki_url(character_tag: str) -> str:
    return f"{settings.danbooru_base_url}/wiki_pages/{quote(character_tag)}"
