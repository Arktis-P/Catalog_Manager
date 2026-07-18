from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all relationships before mapper configuration
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from scripts.v2_reset_for_recollection import reset_for_recollection


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


def make_character(db: Session, tag: str = "sample_character", **overrides) -> GlobalCharacter:
    values = {
        "character_tag": tag,
        "display_name": tag.replace("_", " ").title(),
        "post_count": 100,
        "collect_status": "completed",
        "appearance_status": "completed",
        "gender_status": "completed",
        "series_status": "completed",
        "hair_color": "black_hair",
        "hair_shape": "long_hair",
        "multi_color_hair": "streaked_hair",
        "eye_color": "blue_eyes",
        "feature_tags": "glasses",
        "gender": "1girl",
        "primary_hair_color": "black_hair",
        "primary_hair_needs_review": True,
        "base_prompt": "sample prompt",
        "previous_base_prompt": "old prompt",
        "generation_status": "generation_failed",
        "generation_attempts": 2,
        "total_generation_attempts": 5,
        "prompt_variant_attempts": "variant",
        "last_failure_reason": "quality",
        "prompt_revision_reason": "fix",
        "prompt_revision_level": 2,
        "error_message": "failed",
    }
    values.update(overrides)
    character = GlobalCharacter(**values)
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def make_image(db: Session, character: GlobalCharacter, image_path: str) -> GlobalCharacterImage:
    image = GlobalCharacterImage(global_character_id=character.id, image_path=image_path, is_cover=True)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def make_review(db: Session, character: GlobalCharacter, cover_image_id: int | None) -> GlobalCharacterReview:
    review = GlobalCharacterReview(
        global_character_id=character.id,
        cover_image_id=cover_image_id,
        gender="1girl",
        rating=4,
        final_prompt="final",
        selected_tags="blue_eyes",
        review_status="approved",
        review_note="keep me",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def add_relevance(db: Session, character: GlobalCharacter, tag: str = "blue_eyes") -> None:
    db.add(
        CharacterAppearanceTagRelevance(
            global_character_id=character.id,
            tag=tag,
            tag_category="eye_color",
            cooccurrence_count=30,
            character_post_count=100,
            relevance_score=0.3,
        )
    )
    db.commit()


def write_file(root: Path, relative_path: str, content: bytes = b"image") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_dry_run_does_not_change_database_or_files(db: Session, tmp_path: Path) -> None:
    character = make_character(db)
    image_path = "output/generated_images/pending_review/sample.png"
    image = make_image(db, character, image_path)
    review = make_review(db, character, image.id)
    add_relevance(db, character)
    file_path = write_file(tmp_path, image_path)
    orphan_path = write_file(tmp_path, "output/generated_images/catalog_selected/orphan.png")

    summary = reset_for_recollection(db, project_root=tmp_path, apply=False, scope="all")

    db.refresh(character)
    db.refresh(review)
    assert summary.dry_run is True
    assert summary.character_count == 1
    assert summary.image_rows == 1
    assert summary.relevance_rows == 1
    assert db.query(GlobalCharacterImage).count() == 1
    assert db.query(CharacterAppearanceTagRelevance).count() == 1
    assert character.generation_status == "generation_failed"
    assert review.review_status == "approved"
    assert file_path.exists()
    assert orphan_path.exists()


def test_apply_images_deletes_rows_files_and_resets_review_and_generation(
    db: Session, tmp_path: Path
) -> None:
    character = make_character(db)
    image_path = "output/generated_images/pending_review/sample.png"
    image = make_image(db, character, image_path)
    review = make_review(db, character, image.id)
    file_path = write_file(tmp_path, image_path)
    orphan_path = write_file(tmp_path, "output/generated_images/thumbs/pending_review/384/orphan.webp")

    summary = reset_for_recollection(db, project_root=tmp_path, apply=True, scope="images")

    db.refresh(character)
    db.refresh(review)
    assert summary.image_rows == 1
    assert summary.review_rows == 1
    assert db.query(GlobalCharacterImage).count() == 0
    assert not file_path.exists()
    assert not orphan_path.exists()
    assert review.cover_image_id is None
    assert review.review_status == "pending"
    assert review.final_prompt is None
    assert review.selected_tags is None
    assert review.rating == 4
    assert review.gender == "1girl"
    assert review.review_note == "keep me"
    assert character.generation_status == "not_generated"
    assert character.generation_attempts == 0
    assert character.total_generation_attempts == 0
    assert character.prompt_variant_attempts is None
    assert character.last_failure_reason is None
    assert character.prompt_revision_reason is None
    assert character.prompt_revision_level is None
    assert character.error_message is None


def test_apply_appearance_deletes_relevance_and_clears_columns(db: Session, tmp_path: Path) -> None:
    character = make_character(db)
    add_relevance(db, character)

    summary = reset_for_recollection(db, project_root=tmp_path, apply=True, scope="appearance")

    db.refresh(character)
    assert summary.relevance_rows == 1
    assert db.query(CharacterAppearanceTagRelevance).count() == 0
    assert character.hair_color is None
    assert character.hair_shape is None
    assert character.multi_color_hair is None
    assert character.eye_color is None
    assert character.feature_tags is None
    assert character.primary_hair_color is None
    assert character.primary_hair_needs_review is False
    assert character.base_prompt is None
    assert character.previous_base_prompt is None
    assert character.appearance_status == "uncollected"
    assert character.collect_status == "partial"


def test_character_tag_filter_does_not_touch_other_character(db: Session, tmp_path: Path) -> None:
    target = make_character(db, tag="target_character")
    other = make_character(db, tag="other_character")
    target_image_path = "output/generated_images/pending_review/target.png"
    other_image_path = "output/generated_images/pending_review/other.png"
    target_image = make_image(db, target, target_image_path)
    other_image = make_image(db, other, other_image_path)
    make_review(db, target, target_image.id)
    other_review = make_review(db, other, other_image.id)
    add_relevance(db, target, "fang")
    add_relevance(db, other, "mole")
    target_file = write_file(tmp_path, target_image_path)
    other_file = write_file(tmp_path, other_image_path)

    reset_for_recollection(
        db,
        project_root=tmp_path,
        apply=True,
        scope="all",
        character_tag="target_character",
    )

    db.refresh(target)
    db.refresh(other)
    db.refresh(other_review)
    assert not target_file.exists()
    assert other_file.exists()
    assert db.query(GlobalCharacterImage).filter_by(global_character_id=target.id).count() == 0
    assert db.query(GlobalCharacterImage).filter_by(global_character_id=other.id).count() == 1
    assert db.query(CharacterAppearanceTagRelevance).filter_by(global_character_id=target.id).count() == 0
    assert db.query(CharacterAppearanceTagRelevance).filter_by(global_character_id=other.id).count() == 1
    assert target.appearance_status == "uncollected"
    assert other.appearance_status == "completed"
    assert other.generation_status == "generation_failed"
    assert other_review.review_status == "approved"
