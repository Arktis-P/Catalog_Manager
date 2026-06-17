from types import SimpleNamespace

from app.services.series_merge_service import SeriesMergeService, _escape_like_pattern, similarity_score


def _series(tag: str, *, post_count: int = 0, series_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=series_id,
        series_tag=tag,
        display_name="",
        post_count=post_count,
    )


def test_similarity_score_matches_fate_family_tags() -> None:
    child = _series("last_episode_(fate)")
    parent = _series("fate_(series)")
    assert similarity_score(child, parent) > 0


def test_search_results_sort_by_post_count() -> None:
    candidates = [
        _series("fate/stay_night", post_count=5000, series_id=1),
        _series("fate_(series)", post_count=90000, series_id=2),
        _series("fate/zero", post_count=20000, series_id=3),
    ]
    ranked = SeriesMergeService._rank_search_results(candidates, limit=10)
    assert [item.series_tag for item in ranked] == [
        "fate_(series)",
        "fate/zero",
        "fate/stay_night",
    ]


def test_escape_like_pattern_escapes_underscore() -> None:
    assert _escape_like_pattern("fate_(series)") == "fate\\_(series)"


def test_recommendations_prioritize_similarity() -> None:
    anchor = _series("fate/type_redline")
    candidates = [
        _series("unrelated_series", post_count=99999, series_id=1),
        _series("fate_(series)", post_count=1000, series_id=2),
    ]
    ranked = SeriesMergeService._rank_recommendations(anchor, candidates, limit=10)
    assert ranked[0].series_tag == "fate_(series)"
