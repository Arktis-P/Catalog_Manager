from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all relationships before mapper configuration
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.services.generation_service import GenerationService
from app.services.tag_relevance_service import TagRelevanceService


@pytest.fixture()
def db():
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


def make_character(db, **overrides) -> GlobalCharacter:
    values = {
        "character_tag": "sample_character",
        "display_name": "Sample Character",
        "post_count": 100,
    }
    values.update(overrides)
    character = GlobalCharacter(**values)
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


class TestRelevanceUncollectedIds:
    def test_excludes_characters_with_history_and_completed_status(self, db):
        never_collected = make_character(db, character_tag="a", post_count=500, appearance_status="uncollected")
        needs_review = make_character(db, character_tag="b", post_count=300, appearance_status="needs_review")
        db.add(
            CharacterAppearanceTagRelevance(
                global_character_id=needs_review.id, tag="black_hair", tag_category="hair_color"
            )
        )
        fully_done = make_character(db, character_tag="c", post_count=200, appearance_status="completed")
        db.add(
            CharacterAppearanceTagRelevance(
                global_character_id=fully_done.id, tag="red_hair", tag_category="hair_color"
            )
        )
        db.commit()

        ids = TagRelevanceService(db).list_uncollected_ids()

        assert ids == [never_collected.id, needs_review.id]

    def test_orders_by_post_count_desc_then_id_asc_and_applies_min_post_count(self, db):
        low = make_character(db, character_tag="low", post_count=50)
        high = make_character(db, character_tag="high", post_count=900)
        mid_first = make_character(db, character_tag="mid1", post_count=200)
        mid_second = make_character(db, character_tag="mid2", post_count=200)

        ids = TagRelevanceService(db).list_uncollected_ids()
        assert ids == [high.id, mid_first.id, mid_second.id, low.id]

        filtered = TagRelevanceService(db).list_uncollected_ids(min_post_count=200)
        assert filtered == [high.id, mid_first.id, mid_second.id]


class TestV2NotGeneratedIds:
    def test_filters_by_generation_status_and_min_post_count(self, db):
        not_generated_high = make_character(
            db, character_tag="a", post_count=800, generation_status="not_generated"
        )
        not_generated_low = make_character(
            db, character_tag="b", post_count=10, generation_status="not_generated"
        )
        make_character(db, character_tag="c", post_count=900, generation_status="completed")

        ids = GenerationService(db).list_v2_not_generated_ids()
        assert ids == [not_generated_high.id, not_generated_low.id]

        filtered = GenerationService(db).list_v2_not_generated_ids(min_post_count=100)
        assert filtered == [not_generated_high.id]

    def test_empty_when_none_match(self, db):
        make_character(db, character_tag="a", post_count=500, generation_status="completed")

        assert GenerationService(db).list_v2_not_generated_ids() == []
