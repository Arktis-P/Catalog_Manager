from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all relationships before mapper configuration
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.services.tag_relevance_service import RelevanceConfig, TagRelevanceService


class FakeDanbooruClient:
    def __init__(
        self,
        counts: dict[str, int],
        created_at: str = "2020-01-02T03:04:05Z",
        related_payload: dict[str, object] | None = None,
        related_error: Exception | None = None,
    ):
        self.counts = counts
        self.created_at = created_at
        self.related_payload = related_payload or {"related_tags": []}
        self.related_error = related_error
        self.count_calls: list[str] = []
        self.post_calls: list[tuple[str, int]] = []
        self.related_calls: list[tuple[str, int | None]] = []

    def count_posts(self, tags: str) -> int:
        self.count_calls.append(tags)
        return self.counts.get(tags, 0)

    def list_posts(self, *, tags: str, limit: int):
        self.post_calls.append((tags, limit))
        return [{"created_at": self.created_at}]

    def get_related_tags(self, query: str, *, category: int | None = 0) -> dict[str, object]:
        self.related_calls.append((query, category))
        if self.related_error is not None:
            raise self.related_error
        return self.related_payload


@pytest.fixture
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


@pytest.fixture
def config() -> RelevanceConfig:
    return RelevanceConfig(
        min_cooccurrence=2,
        threshold_hair_shape=0.35,
        threshold_multicolor=0.30,
        threshold_eye_color=0.35,
        threshold_feature=0.20,
        small_sample_bonus=0.10,
        min_posts_auto_confirm=20,
        feature_tag_whitelist=("glasses", "tail"),
    )


def make_character(db, **overrides) -> GlobalCharacter:
    values = {
        "character_tag": "sample_character",
        "display_name": "Sample Character",
        "post_count": 50,
        "hair_color": "black_hair, white_hair",
        "hair_shape": "long_hair",
        "multi_color_hair": "streaked_hair",
        "eye_color": "blue_eyes",
        "feature_tags": "glasses",
    }
    values.update(overrides)
    character = GlobalCharacter(**values)
    db.add(character)
    db.commit()
    return character


def rows_by_tag(db) -> dict[str, CharacterAppearanceTagRelevance]:
    return {row.tag: row for row in db.query(CharacterAppearanceTagRelevance).all()}


def test_collect_calculates_thresholds_small_sample_and_primary_hair(db, config):
    character = make_character(db)
    client = FakeDanbooruClient(
        {
            "sample_character": 50,
            "sample_character black_hair": 30,
            "sample_character white_hair": 28,
            "sample_character long_hair": 25,
            "sample_character streaked_hair": 19,
            "sample_character blue_eyes": 23,
            "sample_character glasses": 15,
            "sample_character tail": 1,
        }
    )

    result = TagRelevanceService(db, client=client, config=config).collect_for_character(character)
    rows = rows_by_tag(db)

    assert rows["black_hair"].relevance_score == pytest.approx(0.60)
    assert rows["black_hair"].is_prompt_candidate is True
    assert rows["black_hair"].is_confirmed is True
    assert rows["white_hair"].is_prompt_candidate is False
    assert rows["long_hair"].is_prompt_candidate is True  # 0.35 + 0.10 bonus
    assert rows["streaked_hair"].is_prompt_candidate is False  # 0.38 < 0.40
    assert rows["blue_eyes"].is_prompt_candidate is True  # 0.46 >= 0.45
    assert rows["glasses"].is_prompt_candidate is True  # 0.30 >= 0.30
    assert rows["tail"].is_prompt_candidate is False
    assert result.primary_hair_color == "black_hair"
    assert result.primary_hair_needs_review is True
    assert character.appearance_status == "completed"
    assert character.collect_status == "partial"
    assert character.hair_color == "black_hair"
    assert character.hair_shape == "long_hair"
    assert character.multi_color_hair is None
    assert character.eye_color == "blue_eyes"
    assert character.feature_tags == "glasses"
    assert character.base_prompt == "1.2::sample character::, black hair"
    assert character.primary_hair_color == "black_hair"
    assert character.primary_hair_needs_review is True
    assert character.first_post_at == datetime(2020, 1, 2, 3, 4, 5)
    assert client.related_calls == [("sample_character", 0)]
    assert client.post_calls == [("sample_character order:id_asc", 1)]


def test_collect_marks_status_completed_when_all_sub_statuses_are_completed(db, config):
    character = make_character(
        db,
        gender_status="completed",
        series_status="completed",
        hair_color="black_hair",
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character black_hair": 60,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        }
    )

    TagRelevanceService(db, client=client, config=config).collect_for_character(character)

    assert character.appearance_status == "completed"
    assert character.collect_status == "completed"


def test_under_minimum_posts_marks_candidate_without_confirmation(db, config):
    character = make_character(
        db,
        post_count=10,
        hair_color=None,
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags="glasses",
    )
    client = FakeDanbooruClient(
        {"sample_character": 10, "sample_character glasses": 5, "sample_character tail": 0}
    )

    TagRelevanceService(db, client=client, config=config).collect_for_character(character)
    glasses = rows_by_tag(db)["glasses"]

    assert glasses.is_prompt_candidate is True
    assert glasses.is_confirmed is False


def test_large_sample_does_not_receive_small_sample_bonus(db, config):
    character = make_character(
        db,
        post_count=100,
        hair_color=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character long_hair": 36,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        }
    )

    TagRelevanceService(db, client=client, config=config).collect_for_character(character)

    assert rows_by_tag(db)["long_hair"].is_prompt_candidate is True


def test_upsert_is_idempotent_and_refreshes_values(db, config):
    character = make_character(
        db,
        hair_color="black_hair",
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character black_hair": 60,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        }
    )
    service = TagRelevanceService(db, client=client, config=config)

    service.collect_for_character(character)
    first_count = db.query(CharacterAppearanceTagRelevance).count()
    client.counts["sample_character black_hair"] = 75
    service.collect_for_character(character)

    assert db.query(CharacterAppearanceTagRelevance).count() == first_count
    assert rows_by_tag(db)["black_hair"].cooccurrence_count == 75


def test_equal_hair_scores_are_deterministic_and_need_review(db, config):
    character = make_character(
        db,
        hair_color="white_hair, black_hair",
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character white_hair": 50,
            "sample_character black_hair": 50,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        }
    )

    result = TagRelevanceService(db, client=client, config=config).collect_for_character(character)

    assert result.primary_hair_color == "black_hair"
    assert result.primary_hair_needs_review is True


def test_related_tags_add_only_appearance_candidates(db, config):
    character = make_character(
        db,
        hair_color=None,
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character red_hair": 55,
            "sample_character twintails": 45,
            "sample_character gradient_hair": 40,
            "sample_character green_eyes": 38,
            "sample_character fang": 25,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        },
        related_payload={
            "related_tags": [
                {"tag": {"name": "red_hair", "category": 0}, "frequency": 0.55},
                {"tag": {"name": "twintails", "category": 0}, "frequency": 0.45},
                {"tag": {"name": "gradient_hair", "category": 0}, "frequency": 0.40},
                {"tag": {"name": "green_eyes", "category": 0}, "frequency": 0.38},
                {"tag": {"name": "fang", "category": 0}, "frequency": 0.25},
                {"tag": {"name": "vocaloid", "category": 3}, "frequency": 0.90},
                {"tag": {"name": "solo", "category": 0}, "frequency": 0.80},
            ]
        },
    )

    TagRelevanceService(db, client=client, config=config).collect_for_character(character)
    rows = rows_by_tag(db)

    assert rows["red_hair"].tag_category == "hair_color"
    assert rows["red_hair"].is_prompt_candidate is True
    assert rows["twintails"].tag_category == "hair_shape"
    assert rows["twintails"].is_prompt_candidate is True
    assert rows["gradient_hair"].tag_category == "multicolor"
    assert rows["gradient_hair"].is_prompt_candidate is True
    assert rows["green_eyes"].tag_category == "eye_color"
    assert rows["green_eyes"].is_prompt_candidate is True
    assert rows["fang"].tag_category == "feature"
    assert rows["fang"].is_prompt_candidate is True
    assert "vocaloid" not in rows
    assert "solo" not in rows


def test_related_tags_failure_falls_back_to_existing_candidates(db, config):
    character = make_character(
        db,
        hair_color="black_hair",
        hair_shape=None,
        multi_color_hair=None,
        eye_color=None,
        feature_tags=None,
    )
    client = FakeDanbooruClient(
        {
            "sample_character": 100,
            "sample_character black_hair": 60,
            "sample_character glasses": 0,
            "sample_character tail": 0,
        },
        related_error=RuntimeError("related unavailable"),
    )

    TagRelevanceService(db, client=client, config=config).collect_for_character(character)
    rows = rows_by_tag(db)

    assert client.related_calls == [("sample_character", 0)]
    assert rows["black_hair"].is_prompt_candidate is True
    assert rows["glasses"].is_prompt_candidate is False
    assert rows["tail"].is_prompt_candidate is False
