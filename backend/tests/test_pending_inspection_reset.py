from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.services.identity_checker import IDENTITY_CHECKER_VERSION
from app.services.pending_review_inspection_service import PendingReviewInspectionService
from app.services.quality_checker import QUALITY_CHECKER_VERSION


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


def make_character(db: Session, *, tag: str, auto_note: bool) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated",
        reference_profile='{"sample_count":30}',
        reference_profile_version="v1.0",
    )
    character.images.append(
        GlobalCharacterImage(
            image_path=f"output/generated_images/{tag}.webp",
            quality_status="pass",
            quality_score=0.9,
            quality_reasons="[]",
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_status="pass",
            character_confidence=0.95,
            identity_reasons='["auto_rating_candidate:3:0.95"]',
            identity_checker_version=IDENTITY_CHECKER_VERSION,
            is_provisional=True,
        )
    )
    character.review = GlobalCharacterReview(
        review_status="completed" if auto_note else "pending",
        rating=3 if auto_note else 5,
        rating_stage="primary",
        review_note=(
            "manual-note\nauto_inspection=v1.2;prefill=1;rating=3;confidence=0.95;reason=test;test=1"
            if auto_note
            else "manual-note"
        ),
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_reset_test_results_clears_checker_metadata_and_auto_decision(db: Session) -> None:
    character = make_character(db, tag="auto_test_character", auto_note=True)

    result = PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character)
    db.refresh(character.images[-1])
    db.refresh(character.review)

    image = character.images[-1]
    assert result.requested == 1
    assert result.matched == 1
    assert result.images_reset == 1
    assert result.reviews_reset == 1
    assert result.profiles_reset == 1
    assert image.quality_status is None
    assert image.quality_checker_version is None
    assert image.identity_status is None
    assert image.identity_checker_version is None
    assert image.character_confidence is None
    assert image.is_provisional is False
    assert character.reference_profile is None
    assert character.reference_profile_version is None
    assert character.review.rating is None
    assert character.review.review_status == "pending"
    assert character.review.review_note == "manual-note"


def test_reset_test_results_does_not_remove_manual_rating_without_auto_marker(db: Session) -> None:
    character = make_character(db, tag="manual_character", auto_note=False)

    result = PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character.review)

    assert result.images_reset == 1
    assert result.reviews_reset == 0
    assert character.review.rating == 5
    assert character.review.review_status == "pending"
    assert character.review.review_note == "manual-note"
