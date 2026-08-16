from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.services.reference_profile_service import CharacterReferenceProfile

SEMANTIC_CHECKER_VERSION = "v1.2"

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
OUTFIT_REJECT = 0.67
GENDER_CONFIDENT = 0.72
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


@dataclass(frozen=True)
class SemanticCheckResult:
    status: str  # pass | warning | reject
    reasons: list[str] = field(default_factory=list)
    suggested_rating: int | None = None
    suggested_rating_confidence: float | None = None


def evaluate_semantic_tags(
    tag_scores: Mapping[str, float],
    *,
    reference_profile: CharacterReferenceProfile | None = None,
) -> SemanticCheckResult:
    """Detect expensive-to-review generation failures from existing WD tag scores.

    This intentionally reuses the already-required WD request. It does not load a local
    vision model and does not download any reference image. Reject thresholds are
    conservative because a reject causes regeneration.
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

    suggested_rating: int | None = None
    suggested_confidence: float | None = None

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

        non_human_output = _max_score(scores, NON_HUMAN_OUTPUT_TAGS)
        output_girl = scores.get("1girl", 0.0)
        output_boy = scores.get("1boy", 0.0)

        if reference_profile.non_human_ratio >= REFERENCE_STABLE_RATIO:
            suggested_rating = -1
            suggested_confidence = reference_profile.non_human_ratio
            reasons.append(f"auto_rating_candidate:-1:{suggested_confidence:.2f}")
        elif reference_profile.boy_ratio >= REFERENCE_STABLE_RATIO:
            if output_boy >= GENDER_CONFIDENT and output_girl < 0.35:
                suggested_rating = 1
                suggested_confidence = min(reference_profile.boy_ratio, output_boy)
                reasons.append(f"auto_rating_candidate:1:{suggested_confidence:.2f}")
            elif output_girl >= GENDER_CONFIDENT and output_boy < 0.35:
                suggested_rating = 3
                suggested_confidence = min(reference_profile.boy_ratio, output_girl)
                reasons.append(f"auto_rating_candidate:3:{suggested_confidence:.2f}")
        elif reference_profile.girl_ratio >= REFERENCE_STABLE_RATIO:
            if non_human_output >= GENDER_CONFIDENT:
                status = "reject"
                reasons.append("unexpected_non_human_output")
            elif output_boy >= GENDER_CONFIDENT and output_girl < 0.35:
                status = "reject"
                reasons.append("unexpected_male_output")
            elif output_girl >= GENDER_CONFIDENT and output_boy < 0.35:
                # A normal female result is the common path. Prefill 3 later but never
                # auto-complete it, so 5/6 favorites remain visible to the user.
                suggested_rating = 3
                suggested_confidence = min(reference_profile.girl_ratio, output_girl)
                reasons.append(f"auto_rating_candidate:3:{suggested_confidence:.2f}")

    return SemanticCheckResult(
        status=status,
        reasons=reasons,
        suggested_rating=suggested_rating,
        suggested_rating_confidence=suggested_confidence,
    )
