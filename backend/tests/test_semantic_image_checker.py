from __future__ import annotations

from app.services.reference_profile_service import CharacterReferenceProfile
from app.services.semantic_image_checker import evaluate_semantic_tags, needs_outfit_reference


def profile(**overrides) -> CharacterReferenceProfile:
    values = {
        "version": "v1.0",
        "sample_count": 40,
        "girl_ratio": 0.95,
        "boy_ratio": 0.0,
        "non_human_ratio": 0.0,
        "swimwear_ratio": 0.02,
        "underwear_ratio": 0.0,
        "common_outfit_tags": ("school_uniform",),
    }
    values.update(overrides)
    return CharacterReferenceProfile(**values)


def test_reference_sheet_is_regeneration_reject() -> None:
    result = evaluate_semantic_tags({"character_sheet": 0.91, "1girl": 0.9})
    assert result.status == "reject"
    assert any(reason.startswith("embedded_gallery:") for reason in result.reasons)


def test_multiple_goods_and_character_cards_are_rejected() -> None:
    result = evaluate_semantic_tags(
        {
            "trading_card": 0.78,
            "poster_(object)": 0.66,
            "multiple_girls": 0.73,
        }
    )
    assert result.status == "reject"
    assert "goods_or_screen_character_gallery" in result.reasons


def test_single_print_signal_is_warning_not_hard_reject() -> None:
    result = evaluate_semantic_tags(
        {"printed_shirt": 0.75, "text": 0.7, "1girl": 0.9}
    )
    assert result.status == "warning"
    assert "printed_character_or_goods_possible" in result.reasons


def test_normal_output_does_not_need_danbooru_outfit_reference() -> None:
    assert needs_outfit_reference({"1girl": 0.93, "school_uniform": 0.8}) is False


def test_swimwear_output_requests_outfit_reference() -> None:
    assert needs_outfit_reference({"1girl": 0.93, "bikini": 0.82}) is True


def test_atypical_swimsuit_is_rejected_for_normal_clothes_character() -> None:
    result = evaluate_semantic_tags(
        {"bikini": 0.88, "1girl": 0.94},
        reference_profile=profile(swimwear_ratio=0.03),
        gender_prior="1girl",
    )
    assert result.status == "reject"
    assert any(reason.startswith("atypical_swimwear:") for reason in result.reasons)


def test_swimsuit_is_allowed_when_reference_says_it_is_normal() -> None:
    result = evaluate_semantic_tags(
        {"bikini": 0.88, "1girl": 0.94},
        reference_profile=profile(swimwear_ratio=0.72),
        gender_prior="1girl",
    )
    assert result.status == "pass"
    assert result.suggested_rating == 3


def test_non_human_reference_suggests_minus_one() -> None:
    result = evaluate_semantic_tags(
        {"no_humans": 0.91},
        reference_profile=profile(girl_ratio=0.0, non_human_ratio=0.9),
    )
    assert result.suggested_rating == -1
    assert result.suggested_rating_confidence == 0.9


def test_male_reference_and_male_output_suggest_one() -> None:
    result = evaluate_semantic_tags(
        {"1boy": 0.91, "1girl": 0.04},
        reference_profile=profile(girl_ratio=0.0, boy_ratio=0.88),
        gender_prior="1boy",
    )
    assert result.suggested_rating == 1
    assert result.suggested_rating_confidence == 0.88


def test_male_reference_and_feminized_output_suggest_three_only() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.92, "1boy": 0.08},
        reference_profile=profile(girl_ratio=0.0, boy_ratio=0.9),
        gender_prior="1boy",
    )
    assert result.suggested_rating == 3
    assert result.status == "pass"


def test_normal_female_reference_prefills_three_candidate() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.93, "1boy": 0.04},
        reference_profile=profile(girl_ratio=0.9),
        gender_prior="1girl",
    )
    assert result.suggested_rating == 3
    assert result.suggested_rating_confidence == 0.9
    assert result.status == "pass"


def test_female_reference_with_confident_male_output_is_rejected() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.08, "1boy": 0.91},
        reference_profile=profile(girl_ratio=0.94),
        gender_prior="1girl",
    )
    assert result.status == "reject"
    assert "unexpected_male_output" in result.reasons
