import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all ORM mappers before create_all)
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.schemas.review import V2BulkCompleteItemRequest
from app.services.review_service import ReviewService


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _make_character(db: Session, tag: str) -> GlobalCharacter:
    character = GlobalCharacter(character_tag=tag, display_name=tag)
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_bulk_complete_uses_first_visible_image_as_default_cover(db: Session):
    character = _make_character(db, "char_a")
    rejected = GlobalCharacterImage(
        global_character_id=character.id, image_path="rejected.png", is_rejected=True, cover_score=99.0
    )
    low_score = GlobalCharacterImage(
        global_character_id=character.id, image_path="low.png", is_rejected=False, cover_score=1.0
    )
    high_score = GlobalCharacterImage(
        global_character_id=character.id, image_path="high.png", is_rejected=False, cover_score=5.0
    )
    db.add_all([rejected, low_score, high_score])
    db.commit()
    db.refresh(high_score)

    service = ReviewService(db)
    completed, skipped, failed, results = service.bulk_complete_v2_review_characters(
        [V2BulkCompleteItemRequest(character_id=character.id, rating=5)]
    )

    assert (completed, skipped, failed) == (1, 0, 0)
    assert results == [{"character_id": character.id, "status": "completed"}]

    db.refresh(character)
    assert character.review.review_status == "completed"
    assert character.review.rating == 5
    assert character.review.cover_image_id == high_score.id


def test_bulk_complete_skips_items_without_rating(db: Session):
    character = _make_character(db, "char_b")

    service = ReviewService(db)
    completed, skipped, failed, results = service.bulk_complete_v2_review_characters(
        [V2BulkCompleteItemRequest(character_id=character.id, rating=None)]
    )

    assert (completed, skipped, failed) == (0, 1, 0)
    assert results == [{"character_id": character.id, "status": "skipped"}]
    assert character.review is None


def test_bulk_complete_reports_failed_items_without_affecting_others(db: Session):
    character = _make_character(db, "char_c")

    service = ReviewService(db)
    completed, skipped, failed, results = service.bulk_complete_v2_review_characters(
        [
            V2BulkCompleteItemRequest(character_id=999999, rating=3),
            V2BulkCompleteItemRequest(character_id=character.id, rating=4),
        ]
    )

    assert (completed, skipped, failed) == (1, 0, 1)
    assert results[0]["character_id"] == 999999
    assert results[0]["status"] == "failed"
    assert results[0]["error"]
    assert results[1] == {"character_id": character.id, "status": "completed"}

    db.refresh(character)
    assert character.review.review_status == "completed"
    assert character.review.rating == 4
