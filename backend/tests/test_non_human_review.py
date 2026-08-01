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
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=display_name or tag.replace("_", " ").title(),
        post_count=100,
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


# ── list pagination/order ────────────────────────────────────────────────


def test_list_candidates_orders_by_score_desc_and_paginates(db: Session) -> None:
    series = Series(series_tag="linked_series", display_name="Linked", post_count=10)
    db.add(series)
    db.commit()

    high = make_character(db, tag="high_priority_spirit", gender="no_humans")
    mid = make_character(db, tag="mid_monster_boy", gender="1girl", hair_color="black_hair")
    low = make_character(
        db,
        tag="low_monster_girl",
        gender="1girl",
        hair_color="black_hair",
        series=series,
    )
    not_candidate = make_character(
        db, tag="not_a_candidate", gender="1girl", hair_color="black_hair", series=series
    )

    for character in (high, mid, low, not_candidate):
        apply_recalculation(character)
    db.commit()

    assert high.non_human_candidate_score > mid.non_human_candidate_score > low.non_human_candidate_score
    assert low.non_human_candidate_score >= CANDIDATE_SCORE_THRESHOLD
    assert not_candidate.non_human_candidate_score < CANDIDATE_SCORE_THRESHOLD

    response = review_router.list_non_human_candidates(
        filter_status="pending",
        search=None,
        skip=0,
        limit=2,
        service=NonHumanReviewService(db),
    )
    body = response.model_dump()
    assert body["total"] == 3
    assert [item["character_tag"] for item in body["items"]] == [high.character_tag, mid.character_tag]
    # image-less candidates still serialize with no preview image
    assert body["items"][0]["preview_image"] is None
    assert body["items"][0]["images"] == []

    response_page_2 = review_router.list_non_human_candidates(
        filter_status="pending",
        search=None,
        skip=2,
        limit=2,
        service=NonHumanReviewService(db),
    )
    body_page_2 = response_page_2.model_dump()
    assert [item["character_tag"] for item in body_page_2["items"]] == [low.character_tag]
