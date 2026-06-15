from app.integrations.danbooru.appearance_extractor import (
    RelatedTag,
    extract_appearance_tags,
    extract_eye_color,
    extract_gender,
    extract_hair_color,
    extract_multi_color_hair,
)


def test_multi_color_hair_prefers_priority_tags():
    related = [
        RelatedTag("multicolored_hair", 0.9),
        RelatedTag("streaked_hair", 0.4),
    ]
    assert extract_multi_color_hair(related) == "streaked_hair"


def test_multi_color_hair_uses_fallback_only_when_needed():
    related = [RelatedTag("multicolored_hair", 0.2)]
    assert extract_multi_color_hair(related) == "multicolored_hair"


def test_multi_color_hair_empty_when_no_matches():
    related = [RelatedTag("long_hair", 0.5)]
    assert extract_multi_color_hair(related) is None


def test_hair_color_top_five():
    related = [
        RelatedTag("pink_hair", 0.5),
        RelatedTag("blonde_hair", 0.4),
        RelatedTag("blue_hair", 0.3),
        RelatedTag("brown_hair", 0.2),
        RelatedTag("black_hair", 0.15),
        RelatedTag("green_hair", 0.1),
    ]
    assert extract_hair_color(related) == (
        "pink_hair, blonde_hair, blue_hair, brown_hair, black_hair"
    )


def test_eye_color_heterochromia_pair():
    related = [
        RelatedTag("heterochromia", 0.2),
        RelatedTag("blue_eyes", 0.4),
        RelatedTag("red_eyes", 0.35),
    ]
    assert extract_eye_color(related) == "blue_eyes, red_eyes"


def test_eye_color_single():
    related = [RelatedTag("purple_eyes", 0.4)]
    assert extract_eye_color(related) == "purple_eyes"


def test_extract_gender_human():
    related = [RelatedTag("1girl", 0.8), RelatedTag("1boy", 0.2)]
    assert extract_gender(related) == "1girl"


def test_extract_gender_boy_wins():
    related = [RelatedTag("1boy", 0.7), RelatedTag("1girl", 0.4)]
    assert extract_gender(related) == "1boy"


def test_extract_gender_no_humans_when_nonhuman_score_higher():
    related = [RelatedTag("monster", 0.4), RelatedTag("1girl", 0.3)]
    assert extract_gender(related) == "no_humans"


def test_extract_gender_human_wins_when_higher_than_nonhuman():
    related = [RelatedTag("1girl", 0.6), RelatedTag("creatures", 0.2)]
    assert extract_gender(related) == "1girl"


def test_extract_gender_ignores_other_girl_tags():
    related = [RelatedTag("multiple_girls", 0.5), RelatedTag("1boy", 0.3)]
    assert extract_gender(related) == "1boy"


def test_extract_gender_none_when_only_plural_tags():
    related = [RelatedTag("multiple_girls", 0.5), RelatedTag("2boys", 0.3)]
    assert extract_gender(related) is None


def test_normalize_gender_only_allowed_values():
    from app.integrations.danbooru.appearance_extractor import normalize_gender

    assert normalize_gender("1girl") == "1girl"
    assert normalize_gender("1boy") == "1boy"
    assert normalize_gender("monster") == "no_humans"
    assert normalize_gender("2girls") is None
    assert normalize_gender("solo") is None


def test_extract_appearance_tags_combined():
    related = [
        RelatedTag("long_hair", 0.6),
        RelatedTag("twintails", 0.5),
        RelatedTag("purple_hair", 0.45),
        RelatedTag("purple_eyes", 0.4),
        RelatedTag("glasses", 0.3),
    ]
    result = extract_appearance_tags(related)
    assert result.hair_shape == "long_hair, twintails"
    assert result.hair_color == "purple_hair"
    assert result.eye_color == "purple_eyes"
    assert result.feature_tags == "glasses"
