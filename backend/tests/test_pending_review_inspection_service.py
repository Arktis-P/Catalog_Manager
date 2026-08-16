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


def add_character(
    db: Session,
    *,
    tag: str,
    review_status: str | None,
    checker_current: bool = False,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated",
    )
    character.images.append(
        GlobalCharacterImage(
            image_path=f"output/generated_images/pending_review/{tag}.webp",
            quality_status="pass",
            identity_status="pass",
            quality_checker_version=QUALITY_CHECKER_VERSION if checker_current else "old",
            identity_checker_version=IDENTITY_CHECKER_VERSION if checker_current else "old",
        )
    )
    if review_status is not None:
        character.review = GlobalCharacterReview(
            review_status=review_status,
            rating_stage="primary",
            gender="1girl",
        )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_candidate_query_never_returns_completed_reviews(db: Session) -> None:
    pending = add_character(db, tag="pending_character", review_status="pending")
    no_review = add_character(db, tag="no_review_character", review_status=None)
    add_character(db, tag="completed_character", review_status="completed")
    add_character(db, tag="already_current", review_status="pending", checker_current=True)

    rows = PendingReviewInspectionService(db).candidates(limit=50)
    ids = {character.id for character, _image in rows}

    assert pending.id in ids
    assert no_review.id in ids
    assert len(ids) == 2


def test_rating_three_prefill_stays_pending(db: Session) -> None:
    character = add_character(db, tag="feminized_character", review_status="pending")
    service = PendingReviewInspectionService(db)

    changed = service._prefill_rating(
        character,
        rating=3,
        confidence=0.9,
        reason="test",
    )
    db.commit()
    db.refresh(character.review)

    assert changed is True
    assert character.review.rating == 3
    assert character.review.review_status == "pending"
    assert "prefill=1" in (character.review.review_note or "")


def test_auto_completion_can_keep_full_audit_sample_pending(db: Session) -> None:
    character = add_character(db, tag="audit_character", review_status="pending")
    service = PendingReviewInspectionService(db)

    outcome = service._apply_auto_rating(
        character,
        rating=1,
        confidence=0.95,
        audit_sample_rate=1.0,
        reason="test",
    )
    db.commit()
    db.refresh(character.review)

    assert outcome == "audit"
    assert character.review.rating == 1
    assert character.review.review_status == "pending"
    assert "audit=1" in (character.review.review_note or "")


def test_auto_completion_drops_reference_cache_when_not_audit(db: Session) -> None:
    character = add_character(db, tag="auto_character", review_status="pending")
    character.reference_profile = '{"version":"v1.0","sample_count":30}'
    character.reference_profile_version = "v1.0"
    db.commit()

    service = PendingReviewInspectionService(db)
    outcome = service._apply_auto_rating(
        character,
        rating=-1,
        confidence=0.99,
        audit_sample_rate=0.0,
        reason="test",
    )
    db.commit()
    db.refresh(character)
    db.refresh(character.review)

    assert outcome == "completed"
    assert character.review.rating == -1
    assert character.review.review_status == "completed"
    assert character.reference_profile is None
    assert character.reference_profile_version is None
