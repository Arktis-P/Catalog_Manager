from __future__ import annotations

from pathlib import Path

from app.services.identity_checker import (
    CHARACTER_CONFIDENT_THRESHOLD,
    check_identity,
    evaluate_identity,
)


def test_other_character_string_without_category_metadata_does_not_reject() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.95, "kirisame_marisa": 0.88, "black_hair": 0.60},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=["kirisame_marisa", "izayoi_sakuya"],
    )
    assert result.status == "pass"
    assert result.conflicting_character_tag is None
    assert result.conflicting_character_confidence is None
    assert "conflicting_character_tag" not in result.reasons


def test_known_character_tags_parameter_is_compatibility_only() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.9, "kirisame_marisa": 0.99, "black_hair": 0.8},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=["kirisame_marisa"],
    )
    assert result.status == "pass"
    assert result.conflicting_character_tag is None


def test_character_tag_undetected_warns_not_rejects() -> None:
    result = evaluate_identity(
        {"black_hair": 0.5},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        gender="1girl",
        known_character_tags=["kirisame_marisa"],
    )
    assert result.status == "warning"
    assert result.character_confidence is None
    assert "character_tag_undetected" in result.reasons


def test_boy_character_tag_undetected_warns_not_rejects() -> None:
    result = evaluate_identity(
        {"black_hair": 0.5},
        character_tag="some_boy_character",
        primary_hair_color="black_hair",
        gender="1boy",
        known_character_tags=[],
    )
    assert result.status == "warning"
    assert "boy_character_tag_undetected" in result.reasons


def test_confident_character_tag_with_matching_hair_passes() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.95, "black_hair": 0.80},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=["kirisame_marisa"],
    )
    assert result.status == "pass"
    assert result.character_confidence == 0.95
    assert result.hair_color_confidence == 0.80
    assert result.conflicting_character_tag is None


def test_confident_character_tag_without_expected_hair_color_evidence_warns() -> None:
    # No strong alternate hair → do not spend regeneration budget on weak/absent hair.
    result = evaluate_identity(
        {"hakurei_reimu": 0.95},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=[],
    )
    assert result.status == "pass"
    assert result.hair_color_confidence is None
    assert "hair_color_unknown" in result.reasons
    assert "hair_color_mismatch" not in result.reasons


def test_undetected_character_with_strong_wrong_hair_is_mismatch() -> None:
    result = evaluate_identity(
        {"blonde_hair": 0.72, "1girl": 0.9},
        character_tag="unknown_wd_character",
        primary_hair_color="black_hair",
        gender="1girl",
    )
    assert result.status == "warning"
    assert "character_tag_undetected" in result.reasons
    assert "hair_color_mismatch" in result.reasons
    assert any(r.startswith("hair_color_conflict:blonde_hair:") for r in result.reasons)


def test_undetected_character_with_matching_hair_is_not_mismatch() -> None:
    result = evaluate_identity(
        {"black_hair": 0.55, "1girl": 0.9},
        character_tag="unknown_wd_character",
        primary_hair_color="black_hair",
        gender="1girl",
    )
    assert "character_tag_undetected" in result.reasons
    assert "hair_color_mismatch" not in result.reasons
    assert result.hair_color_confidence == 0.55


def test_undetected_character_with_weak_hair_is_not_mismatch() -> None:
    result = evaluate_identity(
        {"blonde_hair": 0.40, "hat": 0.8},
        character_tag="unknown_wd_character",
        primary_hair_color="black_hair",
        gender="1girl",
    )
    assert "character_tag_undetected" in result.reasons
    assert "hair_color_mismatch" not in result.reasons
    assert "hair_color_unknown" in result.reasons


def test_low_confidence_character_tag_warns() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": CHARACTER_CONFIDENT_THRESHOLD - 0.05, "black_hair": 0.8},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=[],
    )
    assert result.status == "warning"
    assert "character_tag_low_confidence" in result.reasons


def test_unexpected_multicolor_tag_is_suggested_but_does_not_change_verdict() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.95, "black_hair": 0.80, "streaked_hair": 0.65},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        expected_multicolor_tags=[],
        known_character_tags=[],
    )
    assert result.status == "pass"
    assert result.suggested_multicolor_tags == ["streaked_hair"]
    assert "unexpected_multicolor_tag" in result.reasons


def test_expected_multicolor_tag_is_not_suggested_again() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.95, "black_hair": 0.80, "streaked_hair": 0.65},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        expected_multicolor_tags=["streaked_hair"],
        known_character_tags=[],
    )
    assert result.suggested_multicolor_tags == []
    assert "unexpected_multicolor_tag" not in result.reasons


def test_own_character_tag_is_never_treated_as_conflict() -> None:
    result = evaluate_identity(
        {"hakurei_reimu": 0.95, "black_hair": 0.80},
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=["hakurei_reimu"],
    )
    assert result.status == "pass"
    assert result.conflicting_character_tag is None


def test_check_identity_returns_warning_when_hf_token_missing(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")

    # Force the "no token and no local WD" path deterministically: on machines that have
    # the local ONNX model cached, the tokenless path would instead run local inference.
    monkeypatch.setattr(
        "app.integrations.image_tagger.hf_wd_tagger.local_wd_available",
        lambda: False,
    )

    result = check_identity(
        image_path,
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        hf_token=None,
    )
    assert result.status == "warning"
    assert "tagger_unavailable" in result.reasons


def test_check_identity_uses_mocked_tagger_predictions(monkeypatch, tmp_path: Path) -> None:
    from app.integrations.image_tagger.hf_wd_tagger import TagPrediction

    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")

    def fake_predict(*args, **kwargs):
        return (
            [
                TagPrediction(tag="hakurei_reimu", confidence=0.92),
                TagPrediction(tag="black_hair", confidence=0.7),
            ],
            None,
        )

    monkeypatch.setattr(
        "app.integrations.image_tagger.hf_wd_tagger.predict_tags_via_hf", fake_predict
    )

    result = check_identity(
        image_path,
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        known_character_tags=[],
        hf_token="fake-token",
    )
    assert result.status == "pass"
    assert result.character_confidence == 0.92


def test_check_identity_requests_low_prediction_threshold(monkeypatch, tmp_path: Path) -> None:
    # §1: the raw WD floor must stay <= 0.10 so weak gallery/print/small-face cues reach
    # the semantic suspect rules. Identity thresholds are applied separately on the map.
    from app.integrations.image_tagger.hf_wd_tagger import TagPrediction
    from app.services.identity_checker import WD_PREDICTION_THRESHOLD

    assert WD_PREDICTION_THRESHOLD <= 0.10

    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")
    seen: dict[str, float] = {}

    def fake_predict(*args, **kwargs):
        seen["threshold"] = kwargs.get("threshold")
        return ([TagPrediction(tag="hakurei_reimu", confidence=0.92)], None)

    monkeypatch.setattr(
        "app.integrations.image_tagger.hf_wd_tagger.predict_tags_via_hf", fake_predict
    )

    check_identity(
        image_path,
        character_tag="hakurei_reimu",
        known_character_tags=[],
        hf_token="fake-token",
    )
    assert seen["threshold"] == WD_PREDICTION_THRESHOLD
    assert seen["threshold"] <= 0.10


def test_check_identity_returns_warning_on_tagger_error(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"placeholder")

    def fake_predict(*args, **kwargs):
        return [], "boom"

    monkeypatch.setattr(
        "app.integrations.image_tagger.hf_wd_tagger.predict_tags_via_hf", fake_predict
    )

    result = check_identity(
        image_path,
        character_tag="hakurei_reimu",
        primary_hair_color="black_hair",
        hf_token="fake-token",
    )
    assert result.status == "warning"
    assert "tagger_error" in result.reasons
