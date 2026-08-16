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
from app.routers.pending_inspection import _selected_candidates, pending_inspection_stats


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
    with_image: bool,
    completed: bool = False,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated" if with_image else "not_generated",
    )
    if with_image:
        character.images.append(
            GlobalCharacterImage(
                image_path=f"output/generated_images/pending_review/{tag}.webp",
                quality_status="pass",
                identity_status="pass",
                quality_checker_version="old",
                identity_checker_version="old",
            )
        )
    if completed:
        character.review = GlobalCharacterReview(
            review_status="completed",
            rating_stage="primary",
            rating=3,
            gender="1girl",
        )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_stats_distinguish_all_pending_from_pending_with_image(db: Session) -> None:
    with_image = add_character(db, tag="with_image", with_image=True)
    no_image = add_character(db, tag="no_image", with_image=False)
    add_character(db, tag="completed", with_image=True, completed=True)

    stats = pending_inspection_stats(db)

    assert stats["pending_total"] == 2
    assert stats["pending_with_image"] == 1
    assert stats["pending_without_image"] == 1
    assert stats["remaining"] == 1

    rows = _selected_candidates(db, [with_image.id, no_image.id])
    assert [character.id for character, _image in rows] == [with_image.id]
