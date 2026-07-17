from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.series import Series
from app.routers import review as review_router
from app.schemas.review import V2ReviewSaveRequest
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
    review_status: str | None = None,
    rating: int | None = None,
    generation_status: str = "generated",
    quality_status: str | None = "pass",
    identity_status: str | None = "match",
    suggested_multicolor_tags: str | None = None,
    gender: str | None = "1girl",
    series: Series | None = None,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=100,
        gender=gender,
        hair_color="black_hair",
        multi_color_hair="streaked_hair" if tag == "has_multicolor" else None,
        base_prompt=f"1.2::{tag.replace('_', ' ')}::, black hair",
        first_post_at=datetime(2020, 1, 2, 3, 4, 5),
        generation_status=generation_status,
    )
    character.images.append(
        GlobalCharacterImage(
            image_path=f"/tmp/{tag}.png",
            auto_status="pass",
            cover_score=0.9,
            quality_status=quality_status,
            quality_reasons="ok",
            identity_status=identity_status,
            identity_reasons="ok",
            suggested_multicolor_tags=suggested_multicolor_tags,
        )
    )
    if review_status:
        character.review = GlobalCharacterReview(
            review_status=review_status,
            rating=rating,
            rating_stage="primary",
            gender=gender,
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


def test_v2_review_list_filters_and_returns_preview_metadata(db: Session) -> None:
    series = Series(series_tag="touhou", display_name="Touhou", post_count=1000)
    db.add(series)
    db.commit()
    make_character(db, tag="hakurei_reimu", review_status="pending", series=series)
    make_character(
        db,
        tag="kirisame_marisa",
        review_status="completed",
        rating=5,
        generation_status="generation_failed",
        quality_status="fail",
        identity_status="mismatch",
        suggested_multicolor_tags="gradient_hair",
        series=series,
    )

    response = review_router.list_v2_review_characters(
        review_status="completed",
        rating="5",
        quality_status="fail",
        identity_status="mismatch",
        generation_status="generation_failed",
        gender=None,
        series_id=series.id,
        multicolor="suggested",
        prompt_modified=None,
        search=None,
        skip=0,
        limit=30,
        service=ReviewService(db),
    )

    body = response.model_dump()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["character_tag"] == "kirisame_marisa"
    assert item["review_status"] == "completed"
    assert item["preview_image"]["quality_status"] == "fail"
    assert item["preview_image"]["identity_status"] == "mismatch"
    assert item["preview_image"]["suggested_multicolor_tags"] == "gradient_hair"
    assert item["first_post_at"] == "2020-01-02T03:04:05"


def test_v2_review_complete_saves_review_and_previous_base_prompt(db: Session) -> None:
    character = make_character(db, tag="hakurei_reimu")
    old_prompt = character.base_prompt

    response = review_router.complete_v2_review_character(
        character.id,
        V2ReviewSaveRequest(
            rating=4,
            gender="1girl",
            base_prompt="1.2::hakurei reimu::, brown hair",
            selected_tags="brown_hair, red_eyes",
        ),
        service=ReviewService(db),
    )

    body = response.model_dump()
    assert body["review_status"] == "completed"
    assert body["rating"] == 4
    assert body["rating_stage"] == "primary"
    assert body["gender"] == "1girl"
    assert body["previous_base_prompt"] == old_prompt

    db.refresh(character)
    assert character.base_prompt == "1.2::hakurei reimu::, brown hair"
    assert character.previous_base_prompt == old_prompt
    assert character.review.review_status == "completed"
    assert character.review.selected_tags == "brown_hair, red_eyes"


def test_v2_review_partial_save_marks_in_progress(db: Session) -> None:
    character = make_character(db, tag="in_progress_character")

    response = review_router.save_v2_review_character(
        character.id,
        V2ReviewSaveRequest(rating=-1, selected_tags="black_hair"),
        service=ReviewService(db),
    )

    assert response.review_status == "in_progress"
    db.refresh(character)
    assert character.review.review_status == "in_progress"
    assert character.review.rating == -1


def test_v2_review_complete_rejects_invalid_rating() -> None:
    with pytest.raises(ValidationError):
        V2ReviewSaveRequest(rating=7)
