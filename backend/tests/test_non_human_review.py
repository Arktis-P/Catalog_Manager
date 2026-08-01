from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.series import Series
from app.routers import review as review_router
from app.schemas.review import NonHumanConfirmRequest
from app.services.non_human_review_service import (
    CANDIDATE_SCORE_THRESHOLD,
    NonHumanReviewService,
    apply_recalculation,
    recalculate_non_human_candidates,
)
from app.services.review_service import ReviewService


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


def make_character(
    db: Session,
    *,
    tag: str,
    gender: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    hair_shape: str | None = None,
    multi_color_hair: str | None = None,
    feature_tags: str | None = None,
    display_name: str | None = None,
    series: Series | None = None,
    post_count: int = 100,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=display_name or tag.replace("_", " ").title(),
        post_count=post_count,
        gender=gender,
        hair_color=hair_color,
        eye_color=eye_color,
        hair_shape=hair_shape,
        multi_color_hair=multi_color_hair,
        feature_tags=feature_tags,
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


# ── candidate scoring ────────────────────────────────────────────────────


def test_no_humans_gender_is_included_as_candidate(db: Session) -> None:
    character = make_character(db, tag="floating_lantern_spirit", gender="no_humans")

    apply_recalculation(character)
    db.commit()

    assert character.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD
    assert character.non_human_suggested_rating == -1
    evidence = json.loads(character.non_human_evidence)
    assert "gender:no_humans" in evidence


def test_human_gender_record_can_qualify_via_non_human_evidence(db: Session) -> None:
    series = Series(series_tag="mystery_series", display_name="Mystery", post_count=10)
    db.add(series)
    db.commit()

    character = make_character(
        db,
        tag="forest_monster_girl",
        gender="1girl",
        hair_color="green_hair",
        eye_color="green_eyes",
        series=series,
    )

    apply_recalculation(character)
    db.commit()

    assert character.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD
    assert character.non_human_suggested_rating == 3
    evidence = json.loads(character.non_human_evidence)
    assert any(entry.startswith("tag_keyword:") for entry in evidence)


def test_ordinary_human_character_is_not_a_candidate(db: Session) -> None:
    series = Series(series_tag="touhou", display_name="Touhou", post_count=1000)
    db.add(series)
    db.commit()

    character = make_character(
        db,
        tag="hakurei_reimu",
        gender="1girl",
        hair_color="black_hair",
        eye_color="red_eyes",
        hair_shape="short_hair",
        series=series,
    )

    apply_recalculation(character)
    db.commit()

    assert character.non_human_candidate_score < CANDIDATE_SCORE_THRESHOLD
    assert character.non_human_suggested_rating is None


# ── confirm / exclude ────────────────────────────────────────────────────


def test_confirm_non_human_minus_one_uses_v2_persistence_and_marks_confirmed(db: Session) -> None:
    character = make_character(db, tag="lonely_no_humans_a", gender="no_humans")
    apply_recalculation(character)
    db.commit()

    response = review_router.confirm_non_human_candidate(
        character.id,
        NonHumanConfirmRequest(rating=-1),
        service=NonHumanReviewService(db),
    )

    assert response.non_human_review_status == "confirmed"
    assert response.review_status == "completed"
    assert response.rating == -1

    db.refresh(character)
    assert character.non_human_review_status == "confirmed"
    assert character.review is not None
    assert character.review.review_status == "completed"
    assert character.review.rating == -1


def test_confirm_non_human_three_uses_v2_persistence_and_marks_confirmed(db: Session) -> None:
    character = make_character(
        db,
        tag="female_monster_b",
        gender="1girl",
        feature_tags="monster_ears",
    )
    apply_recalculation(character)
    db.commit()

    response = review_router.confirm_non_human_candidate(
        character.id,
        NonHumanConfirmRequest(rating=3),
        service=NonHumanReviewService(db),
    )

    assert response.non_human_review_status == "confirmed"
    assert response.review_status == "completed"
    assert response.rating == 3

    db.refresh(character)
    assert character.non_human_review_status == "confirmed"
    assert character.review.rating == 3


def test_confirm_rejects_ratings_other_than_minus_one_or_three() -> None:
    with pytest.raises(ValidationError):
        NonHumanConfirmRequest(rating=2)


def test_exclude_marks_excluded_but_leaves_normal_review_pending(db: Session) -> None:
    character = make_character(db, tag="lonely_no_humans_c", gender="no_humans")
    apply_recalculation(character)
    db.commit()

    response = review_router.exclude_non_human_candidate(
        character.id,
        service=NonHumanReviewService(db),
    )

    assert response.non_human_review_status == "excluded"
    assert response.review_status is None

    db.refresh(character)
    assert character.non_human_review_status == "excluded"
    assert character.review is None

    # still shows up in general V2 pending review
    pending_items, _ = ReviewService(db).list_v2_review_characters(review_status="pending")
    assert any(item.id == character.id for item in pending_items)

    # no longer in the non-human pending queue
    candidate_items, _ = NonHumanReviewService(db).list_candidates(filter_status="pending")
    assert all(item.id != character.id for item in candidate_items)


def test_exclude_rejects_already_confirmed_character(db: Session) -> None:
    character = make_character(db, tag="lonely_no_humans_d", gender="no_humans")
    apply_recalculation(character)
    db.commit()

    service = NonHumanReviewService(db)
    service.confirm(character.id, rating=-1)

    with pytest.raises(ValueError):
        service.exclude(character.id)

    db.refresh(character)
    assert character.non_human_review_status == "confirmed"


def test_confirm_rejects_already_excluded_character(db: Session) -> None:
    character = make_character(db, tag="lonely_no_humans_e", gender="no_humans")
    apply_recalculation(character)
    db.commit()

    service = NonHumanReviewService(db)
    service.exclude(character.id)

    with pytest.raises(ValueError):
        service.confirm(character.id, rating=-1)

    db.refresh(character)
    assert character.non_human_review_status == "excluded"
    assert character.review is None


def test_action_rejects_character_below_candidate_score_threshold(db: Session) -> None:
    series = Series(series_tag="touhou2", display_name="Touhou2", post_count=1000)
    db.add(series)
    db.commit()

    character = make_character(
        db,
        tag="hakurei_reimu2",
        gender="1girl",
        hair_color="black_hair",
        eye_color="red_eyes",
        hair_shape="short_hair",
        series=series,
    )
    apply_recalculation(character)
    db.commit()
    assert character.non_human_candidate_score < CANDIDATE_SCORE_THRESHOLD
    assert character.non_human_review_status == "pending"

    service = NonHumanReviewService(db)
    with pytest.raises(ValueError):
        service.confirm(character.id, rating=-1)
    with pytest.raises(ValueError):
        service.exclude(character.id)

    db.refresh(character)
    assert character.non_human_review_status == "pending"
    assert character.review is None


# ── recalculation ────────────────────────────────────────────────────────


def test_recalculation_preserves_confirmed_and_excluded_decisions(db: Session) -> None:
    confirmed = make_character(db, tag="decided_confirmed", gender="no_humans")
    excluded = make_character(db, tag="decided_excluded", gender="no_humans")
    apply_recalculation(confirmed)
    apply_recalculation(excluded)
    confirmed.non_human_review_status = "confirmed"
    excluded.non_human_review_status = "excluded"
    db.commit()

    # corrupt the stored score to prove recalculation skips decided rows entirely
    confirmed.non_human_candidate_score = 0.0
    excluded.non_human_candidate_score = 0.0
    db.commit()

    summary = recalculate_non_human_candidates(db)

    assert summary.skipped_decided == 2
    db.refresh(confirmed)
    db.refresh(excluded)
    assert confirmed.non_human_review_status == "confirmed"
    assert confirmed.non_human_candidate_score == 0.0
    assert excluded.non_human_review_status == "excluded"
    assert excluded.non_human_candidate_score == 0.0


def test_recalculation_updates_pending_rows(db: Session) -> None:
    character = make_character(db, tag="not_yet_scored", gender="no_humans")
    assert character.non_human_candidate_score == 0.0

    summary = recalculate_non_human_candidates(db)

    assert summary.updated == 1
    assert summary.skipped_decided == 0
    db.refresh(character)
    assert character.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD


# ── recalculate endpoint (UI button) ─────────────────────────────────────


def test_recalculate_endpoint_populates_pending_queue_and_counts_candidates(db: Session) -> None:
    candidate = make_character(db, tag="new_no_humans_spirit", gender="no_humans")
    non_candidate = make_character(
        db,
        tag="ordinary_ojou_sama",
        gender="1girl",
        hair_color="black_hair",
        eye_color="red_eyes",
        hair_shape="short_hair",
    )
    assert candidate.non_human_candidate_score == 0.0
    assert non_candidate.non_human_candidate_score == 0.0

    response = review_router.recalculate_non_human_candidates_endpoint(character_tag=None, db=db)

    assert response.scanned == 2
    assert response.updated == 2
    assert response.skipped_decided == 0
    assert response.candidate_count == 1

    candidate_items, total = NonHumanReviewService(db).list_candidates(filter_status="pending")
    assert total == 1
    assert candidate_items[0].id == candidate.id

    db.refresh(non_candidate)
    assert non_candidate.non_human_candidate_score < CANDIDATE_SCORE_THRESHOLD


def test_recalculate_endpoint_skips_decided_and_scopes_by_character_tag(db: Session) -> None:
    confirmed = make_character(db, tag="already_confirmed_spirit", gender="no_humans")
    apply_recalculation(confirmed)
    confirmed.non_human_review_status = "confirmed"
    db.commit()
    other = make_character(db, tag="unscoped_candidate", gender="no_humans")

    response = review_router.recalculate_non_human_candidates_endpoint(
        character_tag=confirmed.character_tag, db=db
    )

    assert response.scanned == 1
    assert response.skipped_decided == 1
    assert response.updated == 0
    assert response.candidate_count == 0

    db.refresh(other)
    assert other.non_human_candidate_score == 0.0


# ── list pagination/order ────────────────────────────────────────────────


def test_list_candidates_orders_by_post_count_desc_then_tag_asc_and_paginates(db: Session) -> None:
    """정렬은 non_human_candidate_score가 아니라 post_count DESC, character_tag
    ASC 순서를 엄격히 따른다. mid/low는 post_count가 같아 tag 오름차순으로
    tie-break되어야 한다 ("low_monster_girl" < "mid_monster_boy")."""
    series = Series(series_tag="linked_series", display_name="Linked", post_count=10)
    db.add(series)
    db.commit()

    high = make_character(db, tag="high_priority_spirit", gender="no_humans", post_count=300)
    mid = make_character(
        db, tag="mid_monster_boy", gender="1girl", hair_color="black_hair", post_count=200
    )
    low = make_character(
        db,
        tag="low_monster_girl",
        gender="1girl",
        hair_color="black_hair",
        series=series,
        post_count=200,
    )
    not_candidate = make_character(
        db, tag="not_a_candidate", gender="1girl", hair_color="black_hair", series=series, post_count=999
    )

    for character in (high, mid, low, not_candidate):
        apply_recalculation(character)
    db.commit()

    assert low.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD
    assert not_candidate.non_human_candidate_score < CANDIDATE_SCORE_THRESHOLD

    response = review_router.list_non_human_candidates(
        filter_status="pending",
        rating_filter="all",
        search=None,
        skip=0,
        limit=2,
        service=NonHumanReviewService(db),
    )
    body = response.model_dump()
    assert body["total"] == 3
    assert [item["character_tag"] for item in body["items"]] == [high.character_tag, low.character_tag]
    # image-less candidates still serialize with no preview image
    assert body["items"][0]["preview_image"] is None
    assert body["items"][0]["images"] == []

    response_page_2 = review_router.list_non_human_candidates(
        filter_status="pending",
        rating_filter="all",
        search=None,
        skip=2,
        limit=2,
        service=NonHumanReviewService(db),
    )
    body_page_2 = response_page_2.model_dump()
    assert [item["character_tag"] for item in body_page_2["items"]] == [mid.character_tag]


# ── list rating-presence filter ──────────────────────────────────────────


def test_list_candidates_rating_filter_defaults_to_all(db: Session) -> None:
    character = make_character(db, tag="default_filter_spirit", gender="no_humans")
    apply_recalculation(character)
    db.commit()

    items, total = NonHumanReviewService(db).list_candidates(filter_status="pending")

    assert total == 1
    assert items[0].id == character.id


def test_list_candidates_rating_filter_separates_rated_and_unrated(db: Session) -> None:
    rated = make_character(db, tag="rated_no_humans_spirit", gender="no_humans")
    unrated = make_character(db, tag="unrated_no_humans_spirit", gender="no_humans")
    apply_recalculation(rated)
    apply_recalculation(unrated)
    db.commit()

    ReviewService(db).save_v2_review_character(rated.id, review_status="in_progress", rating=3)

    service = NonHumanReviewService(db)

    all_items, all_total = service.list_candidates(filter_status="pending", rating_filter="all")
    assert all_total == 2
    assert {item.id for item in all_items} == {rated.id, unrated.id}

    rated_items, rated_total = service.list_candidates(filter_status="pending", rating_filter="rated")
    assert rated_total == 1
    assert rated_items[0].id == rated.id

    unrated_items, unrated_total = service.list_candidates(filter_status="pending", rating_filter="unrated")
    assert unrated_total == 1
    assert unrated_items[0].id == unrated.id


def test_list_candidates_rejects_invalid_rating_filter(db: Session) -> None:
    with pytest.raises(ValueError):
        NonHumanReviewService(db).list_candidates(filter_status="pending", rating_filter="not_a_real_filter")
