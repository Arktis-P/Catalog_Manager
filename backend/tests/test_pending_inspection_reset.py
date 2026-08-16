from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.routers.pending_inspection import (
    PendingInspectionResetSelection,
    PendingInspectionSelection,
    reset_selected_pending_inspection,
    run_selected_pending_inspection,
)
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


def make_character(
    db: Session,
    *,
    tag: str,
    auto_note: bool,
    checker_current: bool = True,
    review_status: str = "pending",
    rating: int | None = None,
    review_note: str | None = None,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated",
        reference_profile='{"sample_count":30}',
        reference_profile_version="v1.0",
        reference_profile_updated_at=datetime.now(timezone.utc),
    )
    character.images.append(
        GlobalCharacterImage(
            image_path=f"output/generated_images/{tag}.webp",
            quality_status="pass" if checker_current else None,
            quality_score=0.9 if checker_current else None,
            quality_reasons="[]" if checker_current else None,
            quality_checker_version=QUALITY_CHECKER_VERSION if checker_current else None,
            identity_status="pass" if checker_current else None,
            character_confidence=0.95 if checker_current else None,
            identity_reasons='["auto_rating_candidate:3:0.95"]' if checker_current else None,
            identity_checker_version=IDENTITY_CHECKER_VERSION if checker_current else None,
            is_provisional=True if checker_current else False,
        )
    )
    if review_note is None:
        if auto_note:
            review_note = (
                "manual-note\n"
                "auto_inspection=v1.2;prefill=1;rating=3;confidence=0.95;reason=test;test=1"
            )
            rating = 3 if rating is None else rating
            review_status = "pending"
        else:
            review_note = "manual-note"
            rating = 5 if rating is None else rating

    character.review = GlobalCharacterReview(
        review_status=review_status,
        rating=rating,
        rating_stage="primary",
        review_note=review_note,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def make_pending_uninspected(db: Session, *, tag: str) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated",
    )
    character.images.append(
        GlobalCharacterImage(
            image_path=f"output/generated_images/{tag}.webp",
        )
    )
    character.review = GlobalCharacterReview(
        review_status="pending",
        rating_stage="primary",
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


def test_reset_preserves_manual_note_and_only_strips_test_marker(db: Session) -> None:
    character = make_character(
        db,
        tag="note_preserve",
        auto_note=True,
        review_note=(
            "some_manual_note\n"
            "auto_inspection=v1.2;prefill=1;rating=3;confidence=0.95;reason=test;test=1"
        ),
    )

    PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character.review)

    assert character.review.review_note == "some_manual_note"
    assert character.review.rating is None


def test_reset_does_not_remove_non_test_auto_inspection(db: Session) -> None:
    character = make_character(
        db,
        tag="prod_auto",
        auto_note=False,
        rating=-1,
        review_status="completed",
        review_note="auto_inspection=v1.2;rating=-1;confidence=0.95;audit=0;reason=prod",
    )

    result = PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character.review)

    assert result.reviews_reset == 0
    assert character.review.rating == -1
    assert character.review.review_status == "completed"
    assert character.review.review_note == (
        "auto_inspection=v1.2;rating=-1;confidence=0.95;audit=0;reason=prod"
    )


def test_reset_preserves_user_edited_rating_after_test_marker(db: Session) -> None:
    character = make_character(
        db,
        tag="user_edited",
        auto_note=False,
        rating=5,
        review_status="pending",
        review_note=(
            "manual-note\n"
            "auto_inspection=v1.2;prefill=1;rating=3;confidence=0.95;reason=test;test=1"
        ),
    )

    result = PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character.review)

    assert result.reviews_reset == 1
    assert character.review.rating == 5
    assert character.review.review_status == "pending"
    assert character.review.review_note == "manual-note"


def test_reset_after_regeneration_clears_latest_image_and_requeues(db: Session) -> None:
    character = make_character(db, tag="regen_char", auto_note=True)
    old_path = character.images[0].image_path
    character.images.append(
        GlobalCharacterImage(
            image_path=f"output/generated_images/{character.character_tag}_regen.webp",
            quality_status="pass",
            quality_score=0.88,
            quality_reasons="[]",
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_status="pass",
            character_confidence=0.91,
            identity_reasons='["auto_rating_candidate:3:0.91"]',
            identity_checker_version=IDENTITY_CHECKER_VERSION,
            is_provisional=True,
        )
    )
    db.commit()
    db.refresh(character)

    before_remaining = PendingReviewInspectionService(db).stats()["remaining"]
    result = PendingReviewInspectionService(db).reset_test_results([character.id])
    db.refresh(character)
    latest = max(character.images, key=lambda image: image.id)

    assert result.images_reset == 1
    assert latest.image_path.endswith("_regen.webp")
    assert latest.quality_checker_version is None
    assert latest.identity_checker_version is None
    assert any(image.image_path == old_path for image in character.images)
    assert PendingReviewInspectionService(db).stats()["remaining"] == before_remaining + 1
    assert any(
        row.id == character.id
        for row, _image in PendingReviewInspectionService(db).candidates(limit=50)
    )


def patch_inspection_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.routers.pending_inspection._assert_inspection_ready",
        lambda _db: None,
    )
    monkeypatch.setattr(
        "app.routers.pending_inspection._active_v2_generation_exists",
        lambda: False,
    )


def stub_inspection(monkeypatch: pytest.MonkeyPatch, inspected_tags: list[str] | None = None) -> None:
    def fake_inspect(self, character, image):  # noqa: ANN001
        if inspected_tags is not None:
            inspected_tags.append(character.character_tag)
        image.quality_status = "pass"
        image.quality_score = 0.9
        image.quality_reasons = "[]"
        image.quality_checker_version = QUALITY_CHECKER_VERSION
        image.identity_status = "pass"
        image.character_confidence = 0.95
        image.identity_reasons = '["auto_rating_candidate:3:0.95"]'
        image.identity_checker_version = IDENTITY_CHECKER_VERSION
        image.is_provisional = True
        return image

    monkeypatch.setattr(PendingReviewInspectionService, "_inspect_existing", fake_inspect)


def test_page_test_tracking_is_recorded_server_side(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_pending_uninspected(db, tag="tracked_a")
    second = make_pending_uninspected(db, tag="tracked_b")
    skipped = make_character(db, tag="tracked_skip", auto_note=False, checker_current=True)
    stub_inspection(monkeypatch)
    patch_inspection_router(monkeypatch)

    assert PendingReviewInspectionService(db).stats()["test_tracked"] == 0

    run_selected_pending_inspection(
        payload=PendingInspectionSelection(character_ids=[first.id, second.id, skipped.id]),
        force_recheck=False,
        db=db,
    )

    service = PendingReviewInspectionService(db)
    assert service.tracked_test_character_ids() == [first.id, second.id]
    assert service.stats()["test_tracked"] == 2


def test_reset_without_ids_uses_server_tracking_and_clears_it(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_pending_uninspected(db, tag="server_reset_a")
    second = make_pending_uninspected(db, tag="server_reset_b")
    stub_inspection(monkeypatch)
    patch_inspection_router(monkeypatch)

    run_selected_pending_inspection(
        payload=PendingInspectionSelection(character_ids=[first.id, second.id]),
        db=db,
    )
    before_remaining = PendingReviewInspectionService(db).stats()["remaining"]

    # The UI sends no ids: the server must fall back to what it recorded itself.
    result = reset_selected_pending_inspection(
        payload=PendingInspectionResetSelection(),
        db=db,
    )

    assert result["images_reset"] == 2
    assert result["test_tracked_remaining"] == 0
    service = PendingReviewInspectionService(db)
    assert service.tracked_test_character_ids() == []
    assert service.stats()["remaining"] == before_remaining + 2


def test_reset_without_ids_and_without_tracking_is_rejected(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_inspection_router(monkeypatch)

    with pytest.raises(HTTPException) as excinfo:
        reset_selected_pending_inspection(payload=PendingInspectionResetSelection(), db=db)

    assert excinfo.value.status_code == 400


def test_reset_with_explicit_ids_keeps_untouched_tracking(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_pending_uninspected(db, tag="partial_a")
    second = make_pending_uninspected(db, tag="partial_b")
    stub_inspection(monkeypatch)
    patch_inspection_router(monkeypatch)

    run_selected_pending_inspection(
        payload=PendingInspectionSelection(character_ids=[first.id, second.id]),
        db=db,
    )

    result = reset_selected_pending_inspection(
        payload=PendingInspectionResetSelection(character_ids=[first.id]),
        db=db,
    )

    assert result["images_reset"] == 1
    assert result["test_tracked_remaining"] == 1
    assert PendingReviewInspectionService(db).tracked_test_character_ids() == [second.id]


def test_run_selected_returns_only_actually_inspected_ids(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    inspectable_a = make_pending_uninspected(db, tag="inspect_a")
    inspectable_b = make_pending_uninspected(db, tag="inspect_b")
    skipped_current = make_character(db, tag="already_current", auto_note=False, checker_current=True)

    inspected_tags: list[str] = []

    def fake_inspect(self, character, image):  # noqa: ANN001
        inspected_tags.append(character.character_tag)
        image.quality_status = "pass"
        image.quality_score = 0.9
        image.quality_reasons = "[]"
        image.quality_checker_version = QUALITY_CHECKER_VERSION
        image.identity_status = "pass"
        image.character_confidence = 0.9
        image.identity_reasons = '["auto_rating_candidate:3:0.9"]'
        image.identity_checker_version = IDENTITY_CHECKER_VERSION
        return image

    monkeypatch.setattr(PendingReviewInspectionService, "_inspect_existing", fake_inspect)
    monkeypatch.setattr(
        "app.routers.pending_inspection._assert_inspection_ready",
        lambda _db: None,
    )
    monkeypatch.setattr(
        "app.routers.pending_inspection._active_v2_generation_exists",
        lambda: False,
    )

    payload = PendingInspectionSelection(
        character_ids=[inspectable_a.id, inspectable_b.id, skipped_current.id]
    )
    result = run_selected_pending_inspection(payload=payload, force_recheck=False, db=db)

    assert set(inspected_tags) == {"inspect_a", "inspect_b"}
    assert result["inspected"] == 2
    assert result["inspected_character_ids"] == [inspectable_a.id, inspectable_b.id]
    assert skipped_current.id not in result["inspected_character_ids"]
    assert result["skipped_current_version"] == 1


def test_run_selected_ids_round_trip_reset_requeues_candidates(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_pending_uninspected(db, tag="round_a")
    second = make_pending_uninspected(db, tag="round_b")
    skipped = make_character(db, tag="round_skip", auto_note=False, checker_current=True)

    def fake_inspect(self, character, image):  # noqa: ANN001
        image.quality_status = "pass"
        image.quality_score = 0.9
        image.quality_reasons = "[]"
        image.quality_checker_version = QUALITY_CHECKER_VERSION
        image.identity_status = "pass"
        image.character_confidence = 0.95
        image.identity_reasons = '["auto_rating_candidate:3:0.95"]'
        image.identity_checker_version = IDENTITY_CHECKER_VERSION
        image.is_provisional = True
        return image

    monkeypatch.setattr(PendingReviewInspectionService, "_inspect_existing", fake_inspect)
    monkeypatch.setattr(
        "app.routers.pending_inspection._assert_inspection_ready",
        lambda _db: None,
    )
    monkeypatch.setattr(
        "app.routers.pending_inspection._active_v2_generation_exists",
        lambda: False,
    )

    run_result = run_selected_pending_inspection(
        payload=PendingInspectionSelection(character_ids=[first.id, second.id, skipped.id]),
        force_recheck=False,
        db=db,
    )
    tracked_ids = run_result["inspected_character_ids"]
    assert tracked_ids == [first.id, second.id]

    before_remaining = PendingReviewInspectionService(db).stats()["remaining"]
    reset = PendingReviewInspectionService(db).reset_test_results(tracked_ids)

    assert reset.images_reset == 2
    for character_id in tracked_ids:
        character = db.get(GlobalCharacter, character_id)
        assert character is not None
        latest = max(character.images, key=lambda image: image.id)
        assert latest.quality_checker_version is None
        assert latest.identity_checker_version is None

    assert PendingReviewInspectionService(db).stats()["remaining"] == before_remaining + 2
    candidate_ids = {
        character.id
        for character, _image in PendingReviewInspectionService(db).candidates(limit=50)
    }
    assert first.id in candidate_ids
    assert second.id in candidate_ids
