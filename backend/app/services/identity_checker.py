from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.danbooru.appearance_extractor import (
    HAIR_COLORS,
    MULTI_COLOR_HAIR_FALLBACK,
    MULTI_COLOR_HAIR_PRIORITY,
    STREAK_COLOR_TAGS,
    normalize_gender,
)
from app.services.reference_profile_service import (
    get_pending_reference_context,
    get_reference_profile_for_tag,
)
from app.services.semantic_image_checker import SEMANTIC_CHECKER_VERSION, evaluate_semantic_tags, needs_outfit_reference

# Base identity logic version. Effective stored version also embeds the semantic
# ruleset so pending images are requeued when only semantic rules change.
IDENTITY_CHECKER_BASE_VERSION = "v3.5"
IDENTITY_CHECKER_VERSION = f"{IDENTITY_CHECKER_BASE_VERSION}+semantic-{SEMANTIC_CHECKER_VERSION}"

TAGGER_FAILURE_REASONS = frozenset(
    {
        "tagger_unavailable",
        "tagger_error",
        "tagger_no_predictions",
    }
)


def is_tagger_failure(reasons: Iterable[str] | None) -> bool:
    """True when identity work did not actually run (must not stamp current version)."""
    if not reasons:
        return False
    return any(str(reason) in TAGGER_FAILURE_REASONS for reason in reasons)

# ── 임계값 (조정 가능) ──────────────────────────────────────────────
# Raw WD prediction floor. Deliberately below the semantic suspect thresholds
# (WEAK_CHARACTER_PRINT = 0.10 등) so those compound rules can see the tags at all.
WD_PREDICTION_THRESHOLD = 0.10
CHARACTER_CONFLICT_THRESHOLD = 0.75    # 다른 캐릭터 태그 고신뢰 판정 → reject
CHARACTER_DETECT_THRESHOLD = 0.35      # 캐릭터 태그 검출 최소 기준(미만이면 미검출)
CHARACTER_CONFIDENT_THRESHOLD = 0.5    # "고신뢰 검출" 기준 (pass 후보에 필요)
HAIR_COLOR_MATCH_THRESHOLD = 0.30
# Strong alternate hair evidence used only when the expected primary colour is weak.
# Tuned conservatively so hats/occlusion do not flood regeneration.
HAIR_COLOR_CONFLICT_THRESHOLD = 0.55
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


HAIR_COLOR_VOCABULARY: frozenset[str] = frozenset(_normalize_tag(tag) for tag in HAIR_COLORS)

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


def _strongest_conflicting_hair(
    tag_scores: dict[str, float],
    *,
    expected_hair_tags: set[str],
) -> tuple[str, float] | None:
    """Return the strongest non-expected hair colour at/above the conflict threshold."""
    best: tuple[str, float] | None = None
    for tag in HAIR_COLOR_VOCABULARY:
        if tag in expected_hair_tags:
            continue
        score = tag_scores.get(tag, 0.0)
        if score < HAIR_COLOR_CONFLICT_THRESHOLD:
            continue
        if best is None or score > best[1]:
            best = (tag, score)
    return best


def _append_hair_appearance_reasons(
    reasons: list[str],
    *,
    normalized_scores: dict[str, float],
    expected_hair_tags: set[str],
    hair_color_confidence: float | None,
) -> None:
    """Evaluate hair independently of character-tag detection.

    character_tag_undetected must not hide an actionable hair mismatch, but weak/absent
    hair evidence alone must not trigger regeneration (hats, occlusion, low light).
    """
    if not expected_hair_tags:
        return
    if hair_color_confidence is not None:
        return
    conflict = _strongest_conflicting_hair(
        normalized_scores, expected_hair_tags=expected_hair_tags
    )
    if conflict is not None:
        conflict_tag, conflict_score = conflict
        reasons.append("hair_color_mismatch")
        reasons.append(f"hair_color_conflict:{conflict_tag}:{conflict_score:.2f}")
        return
    reasons.append("hair_color_unknown")


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

    # Compatibility-only parameter. Current WD tagger predictions expose only
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
    else:
        reasons.append("character_tag_confident")
        status = "pass"

    # Hair is judged after character status so WD-vocabulary misses still surface
    # clear collected-hair conflicts.
    before_hair = len(reasons)
    _append_hair_appearance_reasons(
        reasons,
        normalized_scores=normalized_scores,
        expected_hair_tags=expected_hair_tags,
        hair_color_confidence=hair_color_confidence,
    )
    if any(str(item).startswith("hair_color_mismatch") or item == "hair_color_mismatch" for item in reasons[before_hair:]):
        status = "warning"

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
    # Semantic automation is pending-only. Completed characters must never be pulled
    # back into automatic regeneration/rating merely because a later manual action
    # happens to run the identity checker again.
    try:
        context = get_pending_reference_context(character_tag)
    except Exception:
        # Keep the pre-existing identity result usable in isolated tests, migrations,
        # or transient DB failures instead of turning an optional automation layer into
        # a generation blocker.
        context = None
    if context is None:
        return base

    # The six-figure pending queue must not trigger one Danbooru request per image.
    # Read cheap local priors first. A compact `{tag} solo` metadata profile is fetched
    # only when this specific generated image already looks like swimwear/underwear.
    profile = context.cached_profile
    reference_note: str | None = None
    if needs_outfit_reference(tag_scores):
        if profile is not None:
            reference_note = "reference_loaded"
        else:
            try:
                profile = get_reference_profile_for_tag(character_tag, build_if_missing=True)
            except Exception:
                profile = None
                reference_note = "reference_fetch_failed"
            else:
                if profile is None:
                    reference_note = "reference_insufficient"
                elif not profile.has_stable_sample:
                    reference_note = "reference_insufficient"
                else:
                    reference_note = "reference_loaded"
    else:
        reference_note = "reference_not_needed"

    semantic = evaluate_semantic_tags(
        tag_scores,
        reference_profile=profile,
        gender_prior=gender,
        non_human_candidate_score=context.non_human_candidate_score,
    )

    rank = {"pass": 0, "warning": 1, "reject": 2}
    status = base.status
    if rank.get(semantic.status, 0) > rank.get(status, 0):
        status = semantic.status

    reasons = list(base.reasons)
    for reason in semantic.reasons:
        if reason not in reasons:
            reasons.append(reason)
    if reference_note and reference_note not in reasons:
        reasons.append(reference_note)

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
    """WD tagger 결과로 identity + pending-only semantic 검사를 수행한다.

    Existing local ONNX is preferred and requires no HF token. Remote HF is only a
    fallback when local WD is unavailable. The same WD predictions are reused for
    identity, gallery/print detection, gender/non-human conflict, and conditional outfit
    reference checks.
    """
    from app.integrations.image_tagger.hf_wd_tagger import (
        DEFAULT_HF_WD_MODEL,
        local_wd_available,
        predict_tags_via_hf,
    )

    if not hf_token and not local_wd_available():
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
    # Weak gallery/print/small-face cues live around 0.08–0.15 and must survive the raw
    # prediction cut for the semantic suspect rules to ever fire. Identity/hair/gender and
    # semantic reject thresholds are applied later on this score map, so lowering only the
    # raw floor cannot make automatic rejection more aggressive. Local ONNX computes all
    # logits regardless, so the CPU cost of keeping more low-score tags is negligible.
    threshold = WD_PREDICTION_THRESHOLD
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
