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
from app.services.character_link_service import CharacterLinkService


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


def test_costume_variant_recommends_base_character_as_parent(db: Session) -> None:
    """회귀 케이스: murasaki_shion_(1st_costume)의 1순위 부모 후보는 murasaki_shion이어야
    하며, 포스트 수가 훨씬 높은 무관한 캐릭터(gawr_gura)가 추천되면 안 된다."""
    base = make_character(db, tag="murasaki_shion", post_count=500)
    variant = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=50)
    make_character(db, tag="gawr_gura", post_count=999999)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(variant, limit=10)

    assert ranked, "expected at least one recommended parent candidate"
    assert ranked[0].character.id == base.id
    assert ranked[0].match_reason == "base_tag_match"


def test_costume_variant_recommends_base_character_as_parent_ceres_fauna(db: Session) -> None:
    base = make_character(db, tag="ceres_fauna", post_count=500)
    variant = make_character(db, tag="ceres_fauna_(1st_costume)", post_count=50)
    make_character(db, tag="gawr_gura", post_count=999999)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(variant, limit=10)

    assert ranked, "expected at least one recommended parent candidate"
    assert ranked[0].character.id == base.id
    assert ranked[0].match_reason == "base_tag_match"


def test_disambiguation_parens_do_not_falsely_normalize_match(db: Session) -> None:
    """(genshin_impact) 같은 시리즈 구분 괄호는, 괄호 제거 후의 기본 태그가 실제로
    존재하는 다른 캐릭터가 아니면 정규화 매치로 취급하지 않아야 한다."""
    anchor = make_character(db, tag="amber_(genshin_impact)", post_count=100)
    unrelated = make_character(db, tag="gawr_gura", post_count=999999)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(anchor, limit=10)

    assert all(item.character.id != unrelated.id for item in ranked)


def test_same_series_candidate_is_recommended_over_unrelated(db: Session) -> None:
    series = Series(series_tag="hololive", display_name="Hololive", post_count=1000)
    db.add(series)
    db.commit()

    anchor = make_character(db, tag="totally_unique_anchor_tag", post_count=10, series=series)
    same_series_candidate = make_character(db, tag="another_unrelated_name", post_count=20, series=series)
    make_character(db, tag="yet_another_unrelated_name", post_count=999999)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(anchor, limit=10)

    reasons = {item.character.id: item.match_reason for item in ranked}
    assert reasons.get(same_series_candidate.id) == "same_series"


def test_no_similarity_signal_returns_empty_recommendations(db: Session) -> None:
    """유사도 신호가 전혀 없으면 인기 캐릭터로 fallback하지 않고 빈 목록을 반환한다."""
    anchor = make_character(db, tag="totally_unique_anchor_tag_xyz", post_count=10)
    make_character(db, tag="gawr_gura", post_count=999999)
    make_character(db, tag="hakurei_reimu", post_count=888888)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(anchor, limit=10)

    assert ranked == []


def test_search_mode_filters_by_search_string(db: Session) -> None:
    """§4.2: parent 후보 API가 검색 문자열을 실제로 전달·적용하는지 확인한다."""
    anchor = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=50)
    target = make_character(db, tag="murasaki_shion", post_count=500)
    make_character(db, tag="gawr_gura", post_count=999999)

    service = CharacterLinkService(db)
    ranked = service.list_parent_candidates(anchor, search="shion", limit=10)

    assert ranked
    assert all("shion" in item.character.character_tag for item in ranked)
    assert any(item.character.id == target.id for item in ranked)
