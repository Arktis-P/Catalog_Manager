from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register ORM mappers
from app.database import Base
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.schemas.review import (
    CatalogReviewPurgeUnselectedSelectedRequest,
    GlobalCatalogReviewPurgeUnselectedSelectedRequest,
)
from app.services import review_service
from app.services.character_catalog_service import CharacterCatalogService
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


def _series(db: Session, tag: str = "touhou") -> Series:
    series = Series(series_tag=tag, display_name=tag.title(), post_count=1000)
    db.add(series)
    db.commit()
    db.refresh(series)
    return series


def _series_character(db: Session, series: Series, tag: str, *, status: str = "completed", rating: int | None = 5):
    character = Character(
        series_id=series.id,
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=100,
    )
    character.images = [
        Image(image_path=f"{tag}_selected.png"),
        Image(image_path=f"{tag}_delete.png"),
    ]
    character.review = Review(review_status=status, rating=rating)
    db.add(character)
    db.commit()
    character.review.cover_image_id = character.images[0].id
    db.commit()
    db.refresh(character)
    return character


def _global_character(
    db: Session,
    tag: str,
    *,
    status: str = "completed",
    rating: int | None = 5,
    cover: bool = True,
    image_count: int = 2,
) -> GlobalCharacter:
    character = GlobalCharacter(character_tag=tag, display_name=tag.replace("_", " ").title(), post_count=100)
    character.images = [
        GlobalCharacterImage(image_path=f"{tag}_{index}.png") for index in range(image_count)
    ]
    character.review = GlobalCharacterReview(review_status=status, rating=rating)
    db.add(character)
    db.commit()
    if cover and character.images:
        character.review.cover_image_id = character.images[0].id
    db.commit()
    db.refresh(character)
    return character


def test_global_character_has_cover_filter_and_response_count_terminal_no_cover_reviews(db: Session) -> None:
    terminal = _global_character(db, "terminal_zero", rating=0, cover=False, image_count=0)
    actual_cover = _global_character(db, "actual_cover", rating=5, cover=True)
    missing_cover = _global_character(db, "missing_cover", status="pending", rating=None, cover=False)

    service = CharacterCatalogService(db)

    has_cover_rows, has_cover_total = service.list_characters(has_cover=True, sort_by="id", sort_order="asc")
    missing_rows, missing_total = service.list_characters(has_cover=False, sort_by="id", sort_order="asc")

    assert has_cover_total == 2
    assert [row.id for row in has_cover_rows] == [terminal.id, actual_cover.id]
    assert missing_total == 1
    assert [row.id for row in missing_rows] == [missing_cover.id]

    from app.schemas.character_catalog import GlobalCharacterResponse

    assert GlobalCharacterResponse.from_model(terminal).has_cover_image is True
    assert GlobalCharacterResponse.from_model(actual_cover).has_cover_image is True
    assert GlobalCharacterResponse.from_model(missing_cover).has_cover_image is False


def test_series_purge_preview_and_selected_preserve_review_cover_id(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_service.settings, "project_root", tmp_path)
    series = _series(db)
    character = _series_character(db, series, "hakurei_reimu")
    skipped = _series_character(db, series, "kirisame_marisa", rating=None)
    for image in character.images + skipped.images:
        (tmp_path / image.image_path).write_text("image")

    service = ReviewService(db)
    preview = service.preview_purge_unselected_images(series.id, search="reimu")

    assert preview["item_count"] == 1
    assert preview["image_count"] == 1
    item = preview["items"][0]
    assert item["character_id"] == character.id
    assert item["selected_image"]["id"] == character.review.cover_image_id
    assert [image["id"] for image in item["delete_images"]] == [character.images[1].id]

    affected, removed = service.purge_unselected_images_selected(series.id, [character.id, skipped.id])
    assert (affected, removed) == (1, 1)
    assert (tmp_path / character.images[0].image_path).is_file()
    assert not (tmp_path / f"{character.character_tag}_delete.png").exists()
    assert db.query(Image).filter(Image.character_id == character.id).count() == 1


def test_global_purge_preview_and_selected_delete_all_for_zero_rating_without_selected_cover(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_service.settings, "project_root", tmp_path)
    character = _global_character(db, "no_selected", rating=-1, cover=False)
    ineligible = _global_character(db, "single_selected", rating=5, cover=True, image_count=1)
    unselected_eligible = _global_character(db, "off_scope_eligible", rating=5, cover=True)
    for image in character.images + ineligible.images + unselected_eligible.images:
        (tmp_path / image.image_path).write_text("image")

    service = ReviewService(db)
    preview = service.preview_purge_unselected_images_global(search="selected")

    assert preview["item_count"] == 1
    assert preview["image_count"] == 2
    item = preview["items"][0]
    assert item["character_id"] == character.id
    assert item["selected_image"] is None
    assert {image["id"] for image in item["delete_images"]} == {image.id for image in character.images}

    affected, removed = service.purge_unselected_images_selected_global([character.id, ineligible.id])
    assert (affected, removed) == (1, 2)
    assert db.query(GlobalCharacterImage).filter(GlobalCharacterImage.global_character_id == character.id).count() == 0
    assert db.query(GlobalCharacterImage).filter(GlobalCharacterImage.global_character_id == ineligible.id).count() == 1
    assert (
        db.query(GlobalCharacterImage)
        .filter(GlobalCharacterImage.global_character_id == unselected_eligible.id)
        .count()
        == 2
    )


def test_positive_rating_requires_valid_cover_id_for_preview_and_selected_purge(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_service.settings, "project_root", tmp_path)
    series = _series(db)
    missing_series_cover = _series_character(db, series, "missing_series_cover", rating=5)
    dangling_series_cover = _series_character(db, series, "dangling_series_cover", rating=6)
    missing_series_cover.review.cover_image_id = None
    dangling_series_cover.review.cover_image_id = 999999

    missing_global_cover = _global_character(db, "missing_global_cover", rating=4, cover=False)
    dangling_global_cover = _global_character(db, "dangling_global_cover", rating=3, cover=True)
    dangling_global_cover.review.cover_image_id = 999999
    db.commit()

    all_images = (
        missing_series_cover.images
        + dangling_series_cover.images
        + missing_global_cover.images
        + dangling_global_cover.images
    )
    for image in all_images:
        (tmp_path / image.image_path).write_text("image")

    service = ReviewService(db)

    assert service.preview_purge_unselected_images(series.id)["items"] == []
    assert service.preview_purge_unselected_images_global(search="global_cover")["items"] == []

    assert service.purge_unselected_images_selected(
        series.id,
        [missing_series_cover.id, dangling_series_cover.id],
    ) == (0, 0)
    assert service.purge_unselected_images_selected_global(
        [missing_global_cover.id, dangling_global_cover.id],
    ) == (0, 0)

    assert db.query(Image).filter(Image.character_id.in_([missing_series_cover.id, dangling_series_cover.id])).count() == 4
    assert (
        db.query(GlobalCharacterImage)
        .filter(GlobalCharacterImage.global_character_id.in_([missing_global_cover.id, dangling_global_cover.id]))
        .count()
        == 4
    )
    assert all((tmp_path / image.image_path).is_file() for image in all_images)


def test_selected_request_validation_requires_unique_positive_ids() -> None:
    with pytest.raises(ValueError):
        CatalogReviewPurgeUnselectedSelectedRequest(series_id=1, character_ids=[1, 1])
    with pytest.raises(ValueError):
        GlobalCatalogReviewPurgeUnselectedSelectedRequest(character_ids=[0])


def test_existing_bulk_purge_returns_zero_counts_when_no_candidates(db: Session) -> None:
    series = _series(db)
    service = ReviewService(db)

    assert service.purge_unselected_images_bulk(series.id) == (0, 0)
    assert service.purge_unselected_images_bulk_global() == (0, 0)
