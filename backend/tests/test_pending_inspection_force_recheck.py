from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.routers.pending_inspection import (
    PendingInspectionSelection,
    _selected_candidates,
    run_selected_pending_inspection,
)
from app.services.character_image_service import run_v2_quality_identity_checks
from app.services.identity_checker import (
    IDENTITY_CHECKER_VERSION,
    IdentityCheckResult,
    is_tagger_failure,
)
from app.services.pending_review_inspection_service import PendingReviewInspectionService
from app.services.quality_checker import QUALITY_CHECKER_VERSION
from app.services.semantic_image_checker import SEMANTIC_CHECKER_VERSION


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


def add_pending(db: Session, tag: str, *, stamped: bool = False) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag,
        post_count=100,
        gender="1girl",
        generation_status="generated",
    )
    image = GlobalCharacterImage(image_path=f"output/generated_images/{tag}.webp")
    if stamped:
        image.quality_status = "pass"
        image.quality_checker_version = QUALITY_CHECKER_VERSION
        image.identity_status = "pass"
        image.identity_checker_version = IDENTITY_CHECKER_VERSION
    character.images.append(image)
    character.review = GlobalCharacterReview(review_status="pending", rating_stage="primary")
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_is_tagger_failure_helper() -> None:
    assert is_tagger_failure(["tagger_error"]) is True
    assert is_tagger_failure(["embedded_gallery:collage"]) is False


def test_tagger_error_does_not_stamp_current_identity_version(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    character = add_pending(db, "tagger_fail_char")
    image_path = tmp_path / "x.webp"
    image_path.write_bytes(b"fake")
    character.images[0].image_path = str(image_path.relative_to(tmp_path))
    db.commit()

    monkeypatch.setattr(
        "app.services.character_image_service.settings.project_root",
        tmp_path,
    )
    monkeypatch.setattr(
        "app.services.character_image_service.check_quality",
        lambda _path: type("Q", (), {"status": "pass", "score": 0.9, "reasons": []})(),
    )
    monkeypatch.setattr(
        "app.services.character_image_service.check_identity",
        lambda *_args, **_kwargs: IdentityCheckResult(
            status="warning",
            character_confidence=None,
            hair_color_confidence=None,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=["tagger_error"],
            suggested_multicolor_tags=[],
        ),
    )

    image = run_v2_quality_identity_checks(db, character.images[0], character, hf_token="x")
    assert image.identity_status == "warning"
    assert image.identity_checker_version is None
    assert "tagger_error" in (image.identity_reasons or "")

    service = PendingReviewInspectionService(db)
    candidates = service.candidates(limit=10)
    assert any(row.id == character.id for row, _image in candidates)


def test_page_test_force_recheck_includes_current_versions(db: Session) -> None:
    stamped = add_pending(db, "already_current", stamped=True)
    fresh = add_pending(db, "needs_check", stamped=False)

    forced = _selected_candidates(db, [stamped.id, fresh.id], force_recheck=True)
    incremental = _selected_candidates(db, [stamped.id, fresh.id], force_recheck=False)

    assert {character.id for character, _ in forced} == {stamped.id, fresh.id}
    assert {character.id for character, _ in incremental} == {fresh.id}


def test_production_candidates_skip_current_versions(db: Session) -> None:
    stamped = add_pending(db, "prod_current", stamped=True)
    fresh = add_pending(db, "prod_fresh", stamped=False)
    service = PendingReviewInspectionService(db)
    ids = {character.id for character, _ in service.candidates(limit=10)}
    assert stamped.id not in ids
    assert fresh.id in ids


def test_semantic_version_is_embedded_in_identity_version() -> None:
    assert SEMANTIC_CHECKER_VERSION in IDENTITY_CHECKER_VERSION
    assert "+semantic-" in IDENTITY_CHECKER_VERSION
    assert IDENTITY_CHECKER_VERSION.startswith("v3.")


def test_run_selected_defaults_to_force_recheck(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stamped = add_pending(db, "force_page", stamped=True)

    def fake_inspect(self, character, image):  # noqa: ANN001
        image.quality_status = "pass"
        image.quality_checker_version = QUALITY_CHECKER_VERSION
        image.identity_status = "pass"
        image.identity_reasons = '["auto_rating_candidate:3:0.9"]'
        image.identity_checker_version = IDENTITY_CHECKER_VERSION
        return image

    monkeypatch.setattr(PendingReviewInspectionService, "_inspect_existing", fake_inspect)
    monkeypatch.setattr("app.routers.pending_inspection._assert_inspection_ready", lambda _db: None)
    monkeypatch.setattr("app.routers.pending_inspection._active_v2_generation_exists", lambda: False)

    result = run_selected_pending_inspection(
        payload=PendingInspectionSelection(character_ids=[stamped.id]),
        db=db,
    )
    assert result["inspected"] == 1
    assert stamped.id in result["inspected_character_ids"]
