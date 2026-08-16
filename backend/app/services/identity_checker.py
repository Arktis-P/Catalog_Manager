from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.danbooru.appearance_extractor import (
    MULTI_COLOR_HAIR_FALLBACK,
    MULTI_COLOR_HAIR_PRIORITY,
    STREAK_COLOR_TAGS,
    normalize_gender,
)
from app.services.reference_profile_service import (
    get_pending_reference_context,
    get_reference_profile_for_tag,
)
from app.services.semantic_image_checker import evaluate_semantic_tags, needs_outfit_reference

IDENTITY_CHECKER_VERSION = "v3.1"

# ── 임계값 (조정 가능) ──────────────────────────────────────────────
CHARACTER_CONFLICT_THRESHOLD = 0.75    # 다른 캐릭터 태그 고신뢰 판정 → reject
CHARACTER_DETECT_THRESHOLD = 0.35      # 캐릭터 태그 검출 최소 기준(미만이면 미검출)
CHARACTER_CONFIDENT_THRESHOLD = 0.5    # "고신뢰 검출" 기준 (pass 후보에 필요)
HAIR_COLOR_MATCH_THRESHOLD = 0.30
MULTICOLOR_SUGGEST_THRESHOLD = 0.5

BOY_GENDER = "1boy"

# base_prompt에는 등장하지 않아도 이미지에서 검출되면 "예상하지 않은 multicolor
# 태그"로 추천할 수 있는 어휘. §4.4 목록 + 기존 danbooru 추출기 상수를 재사용한다.
MULTICOLOR_TAG_VOCABULARY: frozenset[str] = frozenset(
    {
        *MULTI_COLOR_HAIR_PRIORITY,
        MULTI_COLOR_HAIR_FALLBACK,
        *STREAK_COLOR_TAGS,
        "two-tone_hair",
        "colored_tips",
    }
)


def _normalize_tag(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


@dataclass(frozen=True)
class IdentityCheckResult:
    status: str  # "pass" | "warning" | "reject"
    character_confidence: float | None
    hair_color_confidence: float | None
    conflicting_character_tag: str | None
    conflicting_character_confidence: float | None
    reasons: list[str] = field(default_factory=list)
    suggested_multicolor_tags: list[str] = field(default_factory=list)


def _max_hair_confidence(
    tag_scores: dict[str, float], expected_hair_tags: set[str]
) -> float | None:
    scores = [
        tag_scores[tag]
        for tag in expected_hair_tags
        if tag_scores.get(tag, 0.0) >= HAIR_COLOR_MATCH_THRESHOLD
    ]
    return max(scores) if scores else None


def _suggest_multicolor_tags(
    tag_scores: dict[str, float], expected_multicolor: set[str]
) -> list[str]:
    suggestions = {
        _normalize_tag(tag)
        for tag, score in tag_scores.items()
        if _normalize_tag(tag) in MULTICOLOR_TAG_VOCABULARY
        and _normalize_tag(tag) not in expected_multicolor
        and score >= MULTICOLOR_SUGGEST_THRESHOLD
    }
    return sorted(suggestions)


def evaluate_identity(
    tag_scores: dict[str, float],
    *,
    character_tag: str,
    primary_hair_color: str | None = None,
    expected_multicolor_tags: Iterable[str] = (),
    gender: str | None = None,
    known_character_tags: Iterable[str] = (),
) -> IdentityCheckResult:
    """base_prompt에 포함된 태그(캐릭터 태그 + 대표 머리색 + 포함된 multicolor)만
    기준으로 WD 태거 예측 결과를 판정한다 (§8.1, §8.2)."""
    own_tag = _normalize_tag(character_tag)
    normalized_scores = {_normalize_tag(tag): score for tag, score in tag_scores.items()}

    expected_multicolor = {_normalize_tag(t) for t in expected_multicolor_tags if t and t.strip()}
    expected_hair_tags: set[str] = set(expected_multicolor)
    if primary_hair_color and primary_hair_color.strip():
        expected_hair_tags.add(_normalize_tag(primary_hair_color))

    # Compatibility-only parameter. Current HF WD tagger predictions expose only
    # tag/score, not WD category metadata, so DB-wide character tag comparison
    # would create false conflicts and force an expensive full-character scan.
    _ = known_character_tags

    hair_color_confidence = _max_hair_confidence(normalized_scores, expected_hair_tags)
    suggested_multicolor = _suggest_multicolor_tags(normalized_scores, expected_multicolor)

    # Conflict detection is skipped until tagger output includes category data.
    character_confidence = normalized_scores.get(own_tag)

    reasons = []
    if suggested_multicolor:
        reasons.append("unexpected_multicolor_tag")

    is_boy = normalize_gender(gender) == BOY_GENDER

    if character_confidence is None or character_confidence < CHARACTER_DETECT_THRESHOLD:
        # 캐릭터 태그 미검출: boy 캐릭터는 reject 금지, warning으로만 표시 (§8.2)
        reasons.append("boy_character_tag_undetected" if is_boy else "character_tag_undetected")
        status = "warning"
    elif character_confidence < CHARACTER_CONFIDENT_THRESHOLD:
        reasons.append("character_tag_low_confidence")
        status = "warning"
    elif expected_hair_tags and hair_color_confidence is None:
        reasons.append("hair_color_mismatch")
        status = "warning"
    else:
        reasons.append("character_tag_confident")
        status = "pass"

    return IdentityCheckResult(
        status=status,
        character_confidence=character_confidence,
        hair_color_confidence=hair_color_confidence,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=reasons,
        suggested_multicolor_tags=suggested_multicolor,
    )


def _merge_semantic_result(
    base: IdentityCheckResult,
    tag_scores: dict[str, float],
    *,
    character_tag: str,
    gender: str | None,
) -> IdentityCheckResult:
    # The six-figure pending queue must not trigger one Danbooru request per image.
    # Read cheap local priors first. A compact `{tag} solo` metadata profile is fetched
    # only when this specific generated image already looks like swimwear/underwear.
    context = get_pending_reference_context(character_tag)
    profile = context.cached_profile if context is not None else None
    non_human_score = context.non_human_candidate_score if context is not None else 0.0

    if context is not None and profile is None and needs_outfit_reference(tag_scores):
        profile = get_reference_profile_for_tag(character_tag, build_if_missing=True)

    semantic = evaluate_semantic_tags(
        tag_scores,
        reference_profile=profile,
        gender_prior=gender,
        non_human_candidate_score=non_human_score,
    )

    rank = {"pass": 0, "warning": 1, "reject": 2}
    status = base.status
    if rank.get(semantic.status, 0) > rank.get(status, 0):
        status = semantic.status

    reasons = list(base.reasons)
    for reason in semantic.reasons:
        if reason not in reasons:
            reasons.append(reason)

    return IdentityCheckResult(
        status=status,
        character_confidence=base.character_confidence,
        hair_color_confidence=base.hair_color_confidence,
        conflicting_character_tag=base.conflicting_character_tag,
        conflicting_character_confidence=base.conflicting_character_confidence,
        reasons=reasons,
        suggested_multicolor_tags=base.suggested_multicolor_tags,
    )


def check_identity(
    image_path: Path,
    *,
    character_tag: str,
    primary_hair_color: str | None = None,
    expected_multicolor_tags: Iterable[str] = (),
    gender: str | None = None,
    known_character_tags: Iterable[str] = (),
    hf_token: str | None = None,
    hf_wd_model: str | None = None,
) -> IdentityCheckResult:
    """HF WD 태거 결과로 identity + low-cost semantic 검사를 수행한다.

    기존 WD 호출 하나를 재사용해 다음을 추가 검출한다.
    - 카드/포스터/화면/캐릭터 시트처럼 의미 없는 이미지 속 이미지 패턴
    - 기존 로컬 성별/non-human 데이터와 생성 결과의 충돌
    - 수영복/속옷 신호가 있을 때만 reference metadata와 기본 복장 비교

    reference baseline은 `{character_tag} solo`의 태그 메타데이터만 사용하며
    Danbooru 이미지를 다운로드하거나 저장하지 않는다.
    """
    from app.integrations.image_tagger.hf_wd_tagger import (
        DEFAULT_HF_WD_MODEL,
        predict_tags_via_hf,
    )

    if not hf_token:
        return IdentityCheckResult(
            status="warning",
            character_confidence=None,
            hair_color_confidence=None,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=["tagger_unavailable"],
            suggested_multicolor_tags=[],
        )

    model = hf_wd_model or DEFAULT_HF_WD_MODEL
    threshold = min(HAIR_COLOR_MATCH_THRESHOLD, CHARACTER_DETECT_THRESHOLD)
    predictions, error = predict_tags_via_hf(
        image_path,
        hf_token=hf_token,
        model=model,
        threshold=threshold,
    )

    if error or not predictions:
        return IdentityCheckResult(
            status="warning",
            character_confidence=None,
            hair_color_confidence=None,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=["tagger_error"] if error else ["tagger_no_predictions"],
            suggested_multicolor_tags=[],
        )

    tag_scores = {p.tag: p.confidence for p in predictions}
    base = evaluate_identity(
        tag_scores,
        character_tag=character_tag,
        primary_hair_color=primary_hair_color,
        expected_multicolor_tags=expected_multicolor_tags,
        gender=gender,
        known_character_tags=known_character_tags,
    )
    return _merge_semantic_result(
        base,
        tag_scores,
        character_tag=character_tag,
        gender=gender,
    )
