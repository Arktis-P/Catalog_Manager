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
    result = evaluate_semantic_tags({"reference_sheet": 0.91, "1girl": 0.9})
    assert result.status == "reject"
    assert any(reason.startswith("embedded_gallery:") for reason in result.reasons)


def test_soft_multiple_views_plus_multi_is_reject() -> None:
    result = evaluate_semantic_tags(
        {
            "multiple_views": 0.40,
            "multiple_girls": 0.45,
            "1girl": 0.55,
        }
    )
    assert result.status == "reject"
    assert "embedded_gallery:multiple_views+multi" in result.reasons


def test_character_print_gallery_is_reject() -> None:
    result = evaluate_semantic_tags(
        {
            "print_shirt": 0.60,
            "character_print": 0.51,
            "1boy": 0.57,
        }
    )
    assert result.status == "reject"
    assert "printed_character_gallery" in result.reasons


def test_poster_collage_with_text_is_reject() -> None:
    result = evaluate_semantic_tags(
        {
            "multiple_girls": 0.87,
            "english_text": 0.18,
            "1girl": 0.4,
        }
    )
    assert result.status == "reject"
    assert "poster_or_collage_with_text" in result.reasons


def test_single_weak_print_shirt_is_not_hard_reject() -> None:
    result = evaluate_semantic_tags({"print_shirt": 0.30, "1girl": 0.9, "solo": 0.8})
    assert result.status == "pass"


def test_weak_print_plus_character_print_is_suspect_not_reject() -> None:
    # §2: a weak print_* + weak character_print pair is no longer strong enough to burn
    # a regeneration. It becomes a human-confirm suspect (warning) instead.
    result = evaluate_semantic_tags(
        {
            "print_shirt": 0.30,
            "character_print": 0.12,
            "1girl": 0.9,
        }
    )
    assert result.status == "warning"
    assert any(reason.startswith("gallery_suspect:character_print") for reason in result.reasons)


def test_weak_print_plus_multi_is_suspect_not_reject() -> None:
    # Confident single subject (1girl high) so the strong multi_subject_output reject does
    # not fire; the weak print + mild multi hint should only raise a suspect.
    result = evaluate_semantic_tags(
        {
            "print_dress": 0.32,
            "multiple_girls": 0.27,
            "1girl": 0.9,
            "solo": 0.85,
        }
    )
    assert result.status == "warning"
    assert any(reason.startswith("gallery_suspect:") for reason in result.reasons)


def test_side_panel_multiple_views_plus_print_is_suspect_not_reject() -> None:
    result = evaluate_semantic_tags(
        {
            "multiple_views": 0.33,
            "print_shirt": 0.30,
            "1girl": 0.8,
        }
    )
    assert result.status == "warning"
    assert any(reason.startswith("gallery_suspect:") for reason in result.reasons)


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


def test_lone_weak_character_print_is_suspect() -> None:
    # A raw character_print around 0.10–0.15 (only reachable after lowering the WD
    # prediction floor) must surface as a suspect, never a silent pass or a reject.
    result = evaluate_semantic_tags({"character_print": 0.12, "1girl": 0.92, "solo": 0.88})
    assert result.status == "warning"
    assert "gallery_suspect:character_print:0.12" in result.reasons


def test_lone_weak_multiple_views_is_suspect() -> None:
    result = evaluate_semantic_tags({"multiple_views": 0.34, "1girl": 0.9})
    assert result.status == "warning"
    assert any(reason.startswith("gallery_suspect:multiple_views") for reason in result.reasons)


def test_single_print_signal_is_warning_not_hard_reject() -> None:
    result = evaluate_semantic_tags(
        {"print_shirt": 0.75, "text": 0.7, "1girl": 0.9}
    )
    assert result.status == "warning"
    assert any(reason.startswith("gallery_suspect:") for reason in result.reasons)


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
    # Local persisted gender is the primary prior; the lower reference ratio does not
    # reduce an already stronger local+output agreement.
    assert result.suggested_rating_confidence == 0.9


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


def test_split_multi_subject_output_is_rejected() -> None:
    # Observed pending-queue failure: the solo score is split across subjects, so no
    # rating candidate was produced and the card stayed silently unrated.
    result = evaluate_semantic_tags(
        {"1girl": 0.52, "multiple_girls": 0.48, "solo": 0.20},
        gender_prior="1girl",
    )
    assert result.status == "reject"
    assert any(reason.startswith("multi_subject_output:multiple_girls:") for reason in result.reasons)


def test_dominant_multi_subject_output_is_rejected_for_male_character() -> None:
    result = evaluate_semantic_tags(
        {"1boy": 0.17, "multiple_girls": 0.85, "multiple_boys": 0.53},
        gender_prior="1boy",
    )
    assert result.status == "reject"
    assert any(reason.startswith("multi_subject_output:multiple_girls:") for reason in result.reasons)


def test_confident_solo_output_with_weak_multi_hint_still_passes() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.81, "multiple_girls": 0.16, "solo": 0.57},
        gender_prior="1girl",
    )
    assert result.status == "pass"
    assert result.suggested_rating == 3
    assert not any(reason.startswith("multi_subject_output:") for reason in result.reasons)


def test_confident_solo_tag_outranks_multi_subject_signal() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.90, "multiple_girls": 0.34, "solo": 0.88},
        gender_prior="1girl",
    )
    assert result.status == "pass"
    assert not any(reason.startswith("multi_subject_output:") for reason in result.reasons)


def test_ambiguous_gender_output_reports_low_confidence_reason() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.50, "1boy": 0.37, "solo": 0.69},
        gender_prior="1boy",
    )
    assert result.suggested_rating is None
    assert "gender_confidence_low:1boy:0.50" in result.reasons


def test_creature_output_without_human_subject_suggests_minus_one() -> None:
    result = evaluate_semantic_tags(
        {"monster": 0.88, "1girl": 0.05},
        gender_prior=None,
    )
    assert result.suggested_rating == -1


def test_robot_output_without_human_subject_suggests_minus_one() -> None:
    result = evaluate_semantic_tags(
        {"mecha": 0.91, "robot": 0.74},
        gender_prior=None,
        non_human_candidate_score=0.6,
    )
    assert result.suggested_rating == -1


def test_equipment_only_output_suggests_minus_one() -> None:
    result = evaluate_semantic_tags(
        {"weapon_focus": 0.80, "1girl": 0.10},
        gender_prior=None,
    )
    assert result.suggested_rating == -1


def test_human_labelled_character_is_never_auto_minus_one() -> None:
    # Gendered characters stay a human decision even when the output looks mechanical.
    for gender in ("1girl", "1boy"):
        result = evaluate_semantic_tags({"mecha": 0.91, "1girl": 0.05}, gender_prior=gender)
        assert result.suggested_rating != -1


def test_creature_output_with_human_subject_does_not_suggest_minus_one() -> None:
    # A girl standing next to a monster must stay a human decision.
    result = evaluate_semantic_tags(
        {"monster": 0.80, "1girl": 0.88, "solo": 0.80},
        gender_prior=None,
    )
    assert result.suggested_rating != -1


def test_female_character_with_creature_output_is_rejected_not_auto_zeroed() -> None:
    result = evaluate_semantic_tags(
        {"monster": 0.90, "1girl": 0.10},
        gender_prior="1girl",
    )
    assert result.status == "reject"
    assert "unexpected_non_human_output" in result.reasons
    assert result.suggested_rating is None


def test_low_confidence_reason_is_not_added_to_rejected_output() -> None:
    result = evaluate_semantic_tags(
        {"1girl": 0.17, "multiple_girls": 0.79},
        gender_prior="1girl",
    )
    assert result.status == "reject"
    assert not any(reason.startswith("gender_confidence_low:") for reason in result.reasons)
