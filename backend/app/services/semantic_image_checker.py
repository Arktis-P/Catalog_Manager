from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.services.reference_profile_service import CharacterReferenceProfile

SEMANTIC_CHECKER_VERSION = "v1.3"

HARD_LAYOUT_TAGS = frozenset(
    {
        "multiple_views",
        "character_sheet",
        "reference_sheet",
        "collage",
        "4koma",
        "comic",
    }
)
GOODS_OR_SCREEN_TAGS = frozenset(
    {
        "trading_card",
        "card",
        "playing_card",
        "poster_(object)",
        "framed_picture",
        "picture_(object)",
        "photo_(object)",
        "monitor",
        "screen",
        "television",
        "phone_screen",
        # Danbooru/WD print tags commonly produced when faces or artwork are rendered
        # onto clothes. These are not a hard reject alone; they become reject-worthy
        # when combined with multiple-subject/gallery evidence below.
        "print_shirt",
        "print_bikini",
        "print_swimsuit",
        "print_bra",
        "print_panties",
        "print_dress",
        "printed_shirt",
        "clothing_print",
    }
)
MULTI_SUBJECT_TAGS = frozenset(
    {
        "multiple_girls",
        "multiple_boys",
        "group",
        "crowd",
    }
)
TEXT_OR_PRINT_TAGS = frozenset(
    {
        "text",
        "english_text",
        "japanese_text",
        "logo",
        "character_name",
    }
)
SWIMWEAR_TAGS = frozenset(
    {
        "bikini",
        "swimsuit",
        "school_swimsuit",
        "one-piece_swimsuit",
        "competition_swimsuit",
        "micro_bikini",
        "string_bikini",
        "swim_briefs",
        "swim_trunks",
    }
)
UNDERWEAR_TAGS = frozenset(
    {
        "underwear",
        "underwear_only",
        "bra",
        "panties",
        "lingerie",
        "sports_bra",
        "boxers",
        "briefs",
    }
)
NON_HUMAN_OUTPUT_TAGS = frozenset({"no_humans", "animal_focus", "creature", "monster", "feral"})

HARD_LAYOUT_REJECT = 0.58
GOODS_SIGNAL = 0.48
OUTFIT_REFERENCE_SIGNAL = 0.55
OUTFIT_REJECT = 0.67
GENDER_CONFIDENT = 0.72
LOCAL_GENDER_PRIOR_CONFIDENCE = 0.90
LOCAL_NO_HUMANS_PRIOR_CONFIDENCE = 0.80
REFERENCE_STABLE_RATIO = 0.72
REFERENCE_ATYPICAL_RATIO = 0.12


def _normalize(tag: str) -> str:
    return tag.strip().lower().replace(" ", "_")


def _normalized_scores(tag_scores: Mapping[str, float]) -> dict[str, float]:
    return {_normalize(tag): float(score) for tag, score in tag_scores.items()}


def _max_score(scores: Mapping[str, float], tags: frozenset[str]) -> float:
    return max((scores.get(tag, 0.0) for tag in tags), default=0.0)


def _active(scores: Mapping[str, float], tags: frozenset[str], threshold: float) -> list[str]:
    return sorted(tag for tag in tags if scores.get(tag, 0.0) >= threshold)


def needs_outfit_reference(tag_scores: Mapping[str, float]) -> bool:
    """Only outputs that look like swimwear/underwear need a Danbooru baseline.

    The common path therefore requires zero Danbooru requests, which matters for a
    six-figure pending queue.
    """
    scores = _normalized_scores(tag_scores)
    return max(_max_score(scores, SWIMWEAR_TAGS), _max_score(scores, UNDERWEAR_TAGS)) >= OUTFIT_REFERENCE_SIGNAL


@dataclass(frozen=True)
class SemanticCheckResult:
    status: str  # pass | warning | reject
    reasons: list[str] = field(default_factory=list)
    suggested_rating: int | None = None
    suggested_rating_confidence: float | None = None


def _apply_gender_prior(
    scores: Mapping[str, float],
    *,
    gender_prior: str | None,
    non_human_candidate_score: float,
    status: str,
    reasons: list[str],
) -> tuple[str, int | None, float | None]:
    """Use already-collected local metadata before considering any network reference."""
    gender = normalize_gender(gender_prior)
    output_girl = scores.get("1girl", 0.0)
    output_boy = scores.get("1boy", 0.0)
    non_human_output = _max_score(scores, NON_HUMAN_OUTPUT_TAGS)

    if gender == "no_humans":
        confidence = max(LOCAL_NO_HUMANS_PRIOR_CONFIDENCE, min(non_human_candidate_score, 1.0))
        reasons.append(f"auto_rating_candidate:-1:{confidence:.2f}")
        return status, -1, confidence

    if gender == "1boy":
        if output_boy >= GENDER_CONFIDENT and output_girl < 0.35:
            confidence = min(LOCAL_GENDER_PRIOR_CONFIDENCE, output_boy)
            reasons.append(f"auto_rating_candidate:1:{confidence:.2f}")
            return status, 1, confidence
        if output_girl >= GENDER_CONFIDENT and output_boy < 0.35:
            confidence = min(LOCAL_GENDER_PRIOR_CONFIDENCE, output_girl)
            reasons.append(f"auto_rating_candidate:3:{confidence:.2f}")
            return status, 3, confidence
        return status, None, None

    if gender == "1girl":
        if non_human_output >= GENDER_CONFIDENT:
            reasons.append("unexpected_non_human_output")
            return "reject", None, None
        if output_boy >= GENDER_CONFIDENT and output_girl < 0.35:
            reasons.append("unexpected_male_output")
            return "reject", None, None
        if output_girl >= GENDER_CONFIDENT and output_boy < 0.35:
            confidence = min(LOCAL_GENDER_PRIOR_CONFIDENCE, output_girl)
            reasons.append(f"auto_rating_candidate:3:{confidence:.2f}")
            return status, 3, confidence

    # A high existing non-human candidate score is useful supporting evidence, but
    # female-like candidates are intentionally not auto-deleted; the dedicated
    # non-human workflow already treats them conservatively.
    if gender != "1girl" and non_human_candidate_score >= 0.85 and non_human_output >= GENDER_CONFIDENT:
        confidence = min(non_human_candidate_score, non_human_output)
        reasons.append(f"auto_rating_candidate:-1:{confidence:.2f}")
        return status, -1, confidence

    return status, None, None


def evaluate_semantic_tags(
    tag_scores: Mapping[str, float],
    *,
    reference_profile: CharacterReferenceProfile | None = None,
    gender_prior: str | None = None,
    non_human_candidate_score: float = 0.0,
) -> SemanticCheckResult:
    """Detect expensive-to-review generation failures from existing WD tag scores.

    This intentionally reuses the already-required WD request. It does not load a local
    vision model and does not download any reference image. The existing local gender
    and non-human signals handle the common path; a Danbooru metadata profile is only
    needed when the generated image itself looks like swimwear/underwear.
    """
    scores = _normalized_scores(tag_scores)
    reasons: list[str] = []
    status = "pass"

    hard_layout = _active(scores, HARD_LAYOUT_TAGS, HARD_LAYOUT_REJECT)
    if hard_layout:
        status = "reject"
        reasons.append(f"embedded_gallery:{','.join(hard_layout[:3])}")

    goods = _active(scores, GOODS_OR_SCREEN_TAGS, GOODS_SIGNAL)
    multi = _active(scores, MULTI_SUBJECT_TAGS, GOODS_SIGNAL)
    print_signals = _active(scores, TEXT_OR_PRINT_TAGS, GOODS_SIGNAL)
    if len(goods) >= 2 or (goods and multi):
        status = "reject"
        reasons.append("goods_or_screen_character_gallery")
    elif goods and print_signals and status != "reject":
        status = "warning"
        reasons.append("printed_character_or_goods_possible")

    status, suggested_rating, suggested_confidence = _apply_gender_prior(
        scores,
        gender_prior=gender_prior,
        non_human_candidate_score=non_human_candidate_score,
        status=status,
        reasons=reasons,
    )

    if reference_profile is not None and reference_profile.has_stable_sample:
        swimwear_score = _max_score(scores, SWIMWEAR_TAGS)
        underwear_score = _max_score(scores, UNDERWEAR_TAGS)

        if (
            swimwear_score >= OUTFIT_REJECT
            and reference_profile.swimwear_ratio <= REFERENCE_ATYPICAL_RATIO
        ):
            status = "reject"
            reasons.append(
                f"atypical_swimwear:{swimwear_score:.2f}/{reference_profile.swimwear_ratio:.2f}"
            )
        if (
            underwear_score >= OUTFIT_REJECT
            and reference_profile.underwear_ratio <= REFERENCE_ATYPICAL_RATIO
        ):
            status = "reject"
            reasons.append(
                f"atypical_underwear:{underwear_score:.2f}/{reference_profile.underwear_ratio:.2f}"
            )

        # Stable reference metadata may upgrade confidence but never downgrade a
        # conservative local decision.
        if reference_profile.non_human_ratio >= REFERENCE_STABLE_RATIO:
            ref_conf = reference_profile.non_human_ratio
            if suggested_rating is None or ref_conf > (suggested_confidence or 0.0):
                suggested_rating = -1
                suggested_confidence = ref_conf
                reasons.append(f"auto_rating_candidate:-1:{ref_conf:.2f}")
        elif reference_profile.boy_ratio >= REFERENCE_STABLE_RATIO:
            output_girl = scores.get("1girl", 0.0)
            output_boy = scores.get("1boy", 0.0)
            if output_boy >= GENDER_CONFIDENT and output_girl < 0.35:
                ref_conf = min(reference_profile.boy_ratio, output_boy)
                if ref_conf > (suggested_confidence or 0.0):
                    suggested_rating = 1
                    suggested_confidence = ref_conf
                    reasons.append(f"auto_rating_candidate:1:{ref_conf:.2f}")
            elif output_girl >= GENDER_CONFIDENT and output_boy < 0.35:
                ref_conf = min(reference_profile.boy_ratio, output_girl)
                if ref_conf > (suggested_confidence or 0.0):
                    suggested_rating = 3
                    suggested_confidence = ref_conf
                    reasons.append(f"auto_rating_candidate:3:{ref_conf:.2f}")

    return SemanticCheckResult(
        status=status,
        reasons=reasons,
        suggested_rating=suggested_rating,
        suggested_rating_confidence=suggested_confidence,
    )
