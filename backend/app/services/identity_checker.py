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

IDENTITY_CHECKER_VERSION = "v2.0"

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

    known_tags = {
        _normalize_tag(t) for t in known_character_tags if t and _normalize_tag(t) != own_tag
    }

    hair_color_confidence = _max_hair_confidence(normalized_scores, expected_hair_tags)
    suggested_multicolor = _suggest_multicolor_tags(normalized_scores, expected_multicolor)

    # 1) 다른 캐릭터 태그 충돌 검사 (최우선 — 명확한 다른 캐릭터로 판단되면 reject)
    conflicting_tag: str | None = None
    conflicting_confidence: float | None = None
    for tag in known_tags:
        score = normalized_scores.get(tag)
        if score is None or score < CHARACTER_CONFLICT_THRESHOLD:
            continue
        if conflicting_confidence is None or score > conflicting_confidence:
            conflicting_tag, conflicting_confidence = tag, score

    character_confidence = normalized_scores.get(own_tag)

    if conflicting_tag is not None:
        reasons = ["conflicting_character_tag"]
        if suggested_multicolor:
            reasons.append("unexpected_multicolor_tag")
        return IdentityCheckResult(
            status="reject",
            character_confidence=character_confidence,
            hair_color_confidence=hair_color_confidence,
            conflicting_character_tag=conflicting_tag,
            conflicting_character_confidence=conflicting_confidence,
            reasons=reasons,
            suggested_multicolor_tags=suggested_multicolor,
        )

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
    """HF WD 태거(기존 연동 재사용)로 이미지를 예측하고 identity 규칙을 적용한다.

    태거를 사용할 수 없거나 예측이 비어 있으면 불확실한 것으로 보고 보수적으로
    warning을 반환한다 (§8.2 "불확실하면 warning").
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
    return evaluate_identity(
        tag_scores,
        character_tag=character_tag,
        primary_hair_color=primary_hair_color,
        expected_multicolor_tags=expected_multicolor_tags,
        gender=gender,
        known_character_tags=known_character_tags,
    )
