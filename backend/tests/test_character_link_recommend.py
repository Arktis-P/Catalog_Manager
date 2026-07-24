from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.series import Series
from app.services.character_link_service import (
    CharacterLinkService,
    ParsedCharacterTag,
    _is_ordered_subsequence,
    _parse_character_tag,
    _structural_relation,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def make_series(db: Session, tag: str) -> Series:
    series = Series(series_tag=tag, display_name=tag.replace("_", " ").title(), post_count=1000)
    db.add(series)
    db.commit()
    db.refresh(series)
    return series


def make_character(db: Session, *, tag: str, post_count: int = 100, series: Series | None = None) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=post_count,
    )
    if series:
        character.series_links.append(
            CharacterSeriesLink(
                series_id=series.id,
                copyright_tag=series.series_tag,
                relevance_rank=0,
                is_primary=True,
            )
        )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def ranked_tags(ranked) -> list[str]:
    return [item.character.character_tag for item in ranked]


def test_parse_character_tag_without_qualifier() -> None:
    assert _parse_character_tag("murasaki_shion") == ParsedCharacterTag(
        base="murasaki_shion",
        qualifiers=(),
    )


def test_parse_character_tag_with_single_qualifier() -> None:
    assert _parse_character_tag("murasaki_shion_(1st_costume)") == ParsedCharacterTag(
        base="murasaki_shion",
        qualifiers=("1st_costume",),
    )


def test_parse_character_tag_with_multiple_qualifiers() -> None:
    assert _parse_character_tag("kitasan_black_(glided_shrine_to_glory)_(umamusume)") == ParsedCharacterTag(
        base="kitasan_black",
        qualifiers=("glided_shrine_to_glory", "umamusume"),
    )


def test_parent_relation_preserves_series_qualifier() -> None:
    anchor = _parse_character_tag("kitasan_black_(glided_shrine_to_glory)_(umamusume)")
    candidate = _parse_character_tag("kitasan_black_(umamusume)")

    relation = _structural_relation(anchor, candidate, role="parent")

    assert relation is not None
    assert relation.tier == 0
    assert relation.removed_count == 1
    assert relation.shared_count == 1


def test_parent_relation_accepts_bare_base() -> None:
    anchor = _parse_character_tag("kitasan_black_(glided_shrine_to_glory)_(umamusume)")
    candidate = _parse_character_tag("kitasan_black")

    relation = _structural_relation(anchor, candidate, role="parent")

    assert relation is not None
    assert relation.tier == 1
    assert relation.removed_count == 2


def test_sibling_variant_is_not_direct_parent() -> None:
    anchor = _parse_character_tag("kitasan_black_(glided_shrine_to_glory)_(umamusume)")
    sibling = _parse_character_tag("kitasan_black_(another_costume)_(umamusume)")
    unrelated_same_series = _parse_character_tag("trainer_(umamusume)")

    assert _structural_relation(anchor, sibling, role="parent") is None
    assert _structural_relation(anchor, unrelated_same_series, role="parent") is None


def test_child_relation_is_symmetric() -> None:
    parent = _parse_character_tag("kitasan_black_(umamusume)")
    child = _parse_character_tag("kitasan_black_(glided_shrine_to_glory)_(umamusume)")

    relation = _structural_relation(parent, child, role="child")

    assert _is_ordered_subsequence(parent.qualifiers, child.qualifiers)
    assert relation is not None
    assert relation.tier == 0
    assert relation.removed_count == 1
    assert relation.shared_count == 1


def test_murasaki_shion_parent_ranked_before_other_hololive_character(db: Session) -> None:
    hololive = make_series(db, "hololive")
    base = make_character(db, tag="murasaki_shion", post_count=500, series=hololive)
    variant = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=50, series=hololive)
    make_character(db, tag="gawr_gura", post_count=999999, series=hololive)

    ranked = CharacterLinkService(db).list_parent_candidates(variant, limit=10)

    assert ranked_tags(ranked)[0] == base.character_tag
    assert ranked[0].match_reason == "structural_parent"


def test_kitasan_black_parent_ranked_before_trainer(db: Session) -> None:
    umamusume = make_series(db, "umamusume")
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=30, series=umamusume)
    anchor = make_character(
        db,
        tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)",
        post_count=10,
        series=umamusume,
    )
    make_character(db, tag="kitasan_black", post_count=100, series=umamusume)
    make_character(db, tag="trainer_(umamusume)", post_count=999999, series=umamusume)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[0] == parent.character_tag
    assert "trainer_(umamusume)" not in ranked_tags(ranked)


def test_kama_parent_preserves_fate_qualifier(db: Session) -> None:
    fate = make_series(db, "fate")
    parent = make_character(db, tag="kama_(fate)", post_count=20, series=fate)
    anchor = make_character(db, tag="kama_(teenager)_(fate)", post_count=10, series=fate)
    make_character(db, tag="kama", post_count=100, series=fate)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[0] == parent.character_tag
    assert ranked[0].match_reason == "structural_parent"


def test_meltryllis_prefers_nearest_existing_parent(db: Session) -> None:
    fate = make_series(db, "fate")
    nearest = make_character(db, tag="meltryllis_(swimsuit_lancer)_(fate)", post_count=10, series=fate)
    broader = make_character(db, tag="meltryllis_(fate)", post_count=999, series=fate)
    anchor = make_character(
        db,
        tag="meltryllis_(swimsuit_lancer)_(first_ascension)_(fate)",
        post_count=5,
        series=fate,
    )

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[:2] == [nearest.character_tag, broader.character_tag]


def test_takakura_ken_parent_preserves_dandadan_qualifier(db: Session) -> None:
    dandadan = make_series(db, "dandadan")
    parent = make_character(db, tag="takakura_ken_(dandadan)", post_count=20, series=dandadan)
    anchor = make_character(db, tag="takakura_ken_(transformed)_(dandadan)", post_count=10, series=dandadan)
    make_character(db, tag="takakura_ken", post_count=100, series=dandadan)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[0] == parent.character_tag


def test_child_recommendation_uses_symmetric_structural_ranking(db: Session) -> None:
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=500)
    child = make_character(db, tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)", post_count=10)
    broader_child = make_character(
        db,
        tag="kitasan_black_(glided_shrine_to_glory)_(victory_pose)_(umamusume)",
        post_count=999,
    )

    ranked = CharacterLinkService(db).list_child_candidates(parent, limit=10)

    assert ranked_tags(ranked)[:2] == [child.character_tag, broader_child.character_tag]
    assert ranked[0].match_reason == "structural_child"


def test_same_series_alone_does_not_create_recommendation(db: Session) -> None:
    hololive = make_series(db, "hololive")
    anchor = make_character(db, tag="totally_unique_anchor_tag", post_count=10, series=hololive)
    same_series_candidate = make_character(db, tag="another_unrelated_name", post_count=999999, series=hololive)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert same_series_candidate.character_tag not in ranked_tags(ranked)


def test_exact_structural_parent_beats_high_post_count_unrelated_character(db: Session) -> None:
    umamusume = make_series(db, "umamusume")
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=1, series=umamusume)
    anchor = make_character(
        db,
        tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)",
        post_count=10,
        series=umamusume,
    )
    make_character(db, tag="trainer_(umamusume)", post_count=999999, series=umamusume)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[0] == parent.character_tag


def test_post_count_is_final_tiebreaker_for_equivalent_structural_candidates(db: Session) -> None:
    anchor = make_character(db, tag="hero_(summer)_(series_a)_(artist_a)", post_count=1)
    lower = make_character(db, tag="hero_(series_a)", post_count=5)
    higher = make_character(db, tag="hero_(artist_a)", post_count=50)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[:2] == [higher.character_tag, lower.character_tag]


def test_manual_search_prioritizes_exact_tag_over_post_count(db: Session) -> None:
    anchor = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=50)
    exact = make_character(db, tag="murasaki_shion", post_count=1)
    make_character(db, tag="murasaki_shion_extra", post_count=999999)

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, search="murasaki_shion", limit=10)

    assert ranked_tags(ranked)[0] == exact.character_tag


def test_existing_link_limits_and_exclude_ids_are_preserved(db: Session) -> None:
    anchor = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=50)
    excluded = make_character(db, tag="murasaki_shion", post_count=500)
    linked_parent = make_character(db, tag="ceres_fauna", post_count=100)
    already_linked = make_character(db, tag="murasaki_shion_(2nd_costume)", post_count=400)
    already_linked.parent_character_id = linked_parent.id
    db.commit()

    ranked_parent = CharacterLinkService(db).list_parent_candidates(anchor, exclude_ids={excluded.id}, limit=10)
    ranked_child = CharacterLinkService(db).list_child_candidates(anchor, limit=10)

    assert excluded.character_tag not in ranked_tags(ranked_parent)
    assert already_linked.character_tag not in ranked_tags(ranked_child)


def test_linkable_parent_is_ranked_before_unlinkable_structural_parent(db: Session) -> None:
    anchor = make_character(db, tag="hero_(summer)_(series)", post_count=10)
    linkable_parent = make_character(db, tag="hero", post_count=1)
    unavailable_parent = make_character(db, tag="hero_(series)", post_count=100)
    unavailable_parent.parent_character_id = linkable_parent.id
    db.commit()

    ranked = CharacterLinkService(db).list_parent_candidates(anchor, limit=10)

    assert ranked_tags(ranked)[0] == linkable_parent.character_tag
