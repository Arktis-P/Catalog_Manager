from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.services.reference_profile_service import CharacterReferenceProfile

SEMANTIC_CHECKER_VERSION = "v1.6"

HARD_LAYOUT_TAGS = frozenset(
    {
        "multiple_views",
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
        "photo_(object)",
        "monitor",
        "screen",
        "television",
        # Strong clothing-print evidence. character_print is the WD tag that most
        # reliably marks face/gallery artwork baked into clothes.
        "character_print",
        "print_shirt",
        "print_bikini",
        "print_swimsuit",
        "print_bra",
        "print_panties",
        "print_dress",
        "clothes_writing",
    }
)
PRINT_CLOTHING_TAGS = frozenset(
    {
        "print_shirt",
        "print_bikini",
        "print_swimsuit",
        "print_bra",
        "print_panties",
        "print_dress",
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
        "clothes_writing",
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
# Combination-only soft thresholds: neither signal alone is enough.
SOFT_LAYOUT_REJECT = 0.35
SOFT_MULTI_REJECT = 0.40
POSTER_MULTI_REJECT = 0.70
POSTER_TEXT_REJECT = 0.15
CHARACTER_PRINT_REJECT = 0.45
PRINT_WITH_CHARACTER_PRINT = 0.25
# Weaker compound gallery signals for print/side-panel misses.
WEAK_PRINT_CLOTHING = 0.28
WEAK_CHARACTER_PRINT = 0.10
WEAK_MULTI_WITH_PRINT = 0.25
WEAK_SIDE_PANEL_VIEWS = 0.30
GOODS_SIGNAL = 0.48
OUTFIT_REFERENCE_SIGNAL = 0.55
OUTFIT_REJECT = 0.67
GENDER_CONFIDENT = 0.72
# A cover image must show one subject. Measured separation on the pending queue: solo
# outputs score multiple_girls <= 0.16 with 1girl >= 0.81, while multi-subject outputs
# split the solo score below GENDER_CONFIDENT and push a multi tag past this floor.
MULTI_SUBJECT_REJECT = 0.30
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


def _append_low_gender_confidence(
    reasons: list[str],
    status: str,
    gender: str,
    score: float,
) -> None:
    """Explain why no rating candidate was produced for a known gender prior.

    Without this the pending card keeps an empty rating and no note, which is
    indistinguishable from an item that was never inspected.
    """
    if status == "reject":
        return
    reasons.append(f"gender_confidence_low:{gender}:{score:.2f}")


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
        _append_low_gender_confidence(reasons, status, gender, max(output_boy, output_girl))
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
        _append_low_gender_confidence(reasons, status, gender, output_girl)

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

    soft_layout = scores.get("multiple_views", 0.0)
    multi_score = _max_score(scores, MULTI_SUBJECT_TAGS)
    if soft_layout >= SOFT_LAYOUT_REJECT and multi_score >= SOFT_MULTI_REJECT and status != "reject":
        # Neither score alone is reject-worthy, but together they match character-sheet /
        # sketch-panel galleries that WD under-tags as hard collage/sheet labels.
        status = "reject"
        reasons.append("embedded_gallery:multiple_views+multi")

    text_score = _max_score(scores, TEXT_OR_PRINT_TAGS)
    if multi_score >= POSTER_MULTI_REJECT and text_score >= POSTER_TEXT_REJECT and status != "reject":
        status = "reject"
        reasons.append("poster_or_collage_with_text")

    character_print = scores.get("character_print", 0.0)
    print_clothing = _active(scores, PRINT_CLOTHING_TAGS, GOODS_SIGNAL)
    weak_print_clothing = _active(scores, PRINT_CLOTHING_TAGS, WEAK_PRINT_CLOTHING)
    if character_print >= CHARACTER_PRINT_REJECT or (
        print_clothing and character_print >= PRINT_WITH_CHARACTER_PRINT
    ):
        status = "reject"
        reasons.append("printed_character_gallery")
    elif status != "reject" and weak_print_clothing and character_print >= WEAK_CHARACTER_PRINT:
        # Weak print_* alone is not enough; require a second print-face cue.
        status = "reject"
        reasons.append("weak_print_gallery")
    elif status != "reject" and weak_print_clothing and multi_score >= WEAK_MULTI_WITH_PRINT:
        status = "reject"
        reasons.append("weak_print_gallery")
    elif (
        status != "reject"
        and soft_layout >= WEAK_SIDE_PANEL_VIEWS
        and (
            character_print >= WEAK_CHARACTER_PRINT
            or multi_score >= WEAK_MULTI_WITH_PRINT
            or bool(weak_print_clothing)
        )
    ):
        # Side-panel / small-face collage often tags as mild multiple_views plus a
        # weak print or multi-subject cue rather than a hard collage label.
        status = "reject"
        reasons.append("embedded_gallery:side_panel")
    elif (
        status != "reject"
        and scores.get("clothes_writing", 0.0) >= WEAK_PRINT_CLOTHING
        and weak_print_clothing
        and multi_score >= WEAK_MULTI_WITH_PRINT
    ):
        status = "reject"
        reasons.append("weak_print_gallery")

    goods = _active(scores, GOODS_OR_SCREEN_TAGS, GOODS_SIGNAL)
    multi = _active(scores, MULTI_SUBJECT_TAGS, GOODS_SIGNAL)
    print_signals = _active(scores, TEXT_OR_PRINT_TAGS, GOODS_SIGNAL)
    if status != "reject" and (len(goods) >= 2 or (goods and multi)):
        status = "reject"
        reasons.append("goods_or_screen_character_gallery")
    elif status != "reject" and print_clothing and multi:
        status = "reject"
        reasons.append("goods_or_screen_character_gallery")
    elif (
        status != "reject"
        and _max_score(scores, frozenset({"poster_(object)", "trading_card", "card", "monitor", "screen"}))
        >= GOODS_SIGNAL
        and text_score >= POSTER_TEXT_REJECT
    ):
        status = "reject"
        reasons.append("poster_or_collage_with_text")
    elif goods and print_signals and status != "reject":
        status = "warning"
        reasons.append("printed_character_or_goods_possible")

    if status != "reject" and multi_score >= MULTI_SUBJECT_REJECT:
        solo_score = max(
            scores.get("solo", 0.0),
            scores.get("1girl", 0.0),
            scores.get("1boy", 0.0),
        )
        if solo_score < GENDER_CONFIDENT:
            multi_tags = _active(scores, MULTI_SUBJECT_TAGS, MULTI_SUBJECT_REJECT)
            top_tag = max(multi_tags, key=lambda tag: scores.get(tag, 0.0), default="multiple")
            status = "reject"
            reasons.append(f"multi_subject_output:{top_tag}:{multi_score:.2f}")

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
