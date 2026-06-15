from app.integrations.danbooru.appearance_extractor import RelatedTag
from app.integrations.danbooru.series_membership import evaluate_series_membership
from app.integrations.danbooru.wiki_dtext import extract_wiki_links, is_list_of_characters_page


def test_extract_wiki_links():
    body = """
    * [[hakurei_reimu]]
    * [[Marisa|kirisame_marisa]]
    * [[touhou]]
    """
    links = extract_wiki_links(body)
    assert "hakurei_reimu" in links
    assert "kirisame_marisa" in links
    assert "touhou" in links


def test_list_of_page_detection():
    assert is_list_of_characters_page("list_of_touhou_project_characters")
    assert not is_list_of_characters_page("touhou")


def test_membership_mismatch():
    result = evaluate_series_membership(
        [
            RelatedTag(name="vocaloid", frequency=0.8),
            RelatedTag(name="touhou", frequency=0.1),
        ],
        expected_series_tag="touhou",
    )
    assert result.is_mismatch


def test_membership_match():
    result = evaluate_series_membership(
        [
            RelatedTag(name="touhou", frequency=0.9),
            RelatedTag(name="vocaloid", frequency=0.1),
        ],
        expected_series_tag="touhou",
    )
    assert not result.is_mismatch
