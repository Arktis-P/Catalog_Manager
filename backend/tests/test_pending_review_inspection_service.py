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
from app.services.inspection_repair import (
    STAGE_IDENTITY_HAIR,
    STAGE_SEMANTIC_GALLERY,
    STAGE_SEMANTIC_OUTFIT,
)
from app.services.pending_review_inspection_service import (
    PendingInspectionSummary,
    PendingReviewInspectionService,
)
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
    quality_status: str = "pass",
    identity_status: str | None = "pass",
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
            quality_status=quality_status,
            identity_status=identity_status,
            quality_checker_version=QUALITY_CHECKER_VERSION if checker_current else "old",
            identity_checker_version=(
                IDENTITY_CHECKER_VERSION if checker_current and identity_status is not None else None
            ),
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


def test_current_quality_reject_does_not_require_identity_version(db: Session) -> None:
    rejected = add_character(
        db,
        tag="quality_reject_audit",
        review_status="pending",
        checker_current=True,
        quality_status="reject",
        identity_status=None,
    )

    rows = PendingReviewInspectionService(db).candidates(limit=50)
    ids = {character.id for character, _image in rows}

    assert rejected.id not in ids


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


def test_candidates_select_latest_image_for_multi_image_character(db: Session) -> None:
    character = GlobalCharacter(
        character_tag="multi_image_char",
        display_name="multi",
        post_count=10,
        gender="1girl",
        generation_status="generated",
    )
    older = GlobalCharacterImage(
        image_path="output/generated_images/pending_review/multi_old.webp",
        quality_status="pass",
        identity_status="pass",
        quality_checker_version="old",
        identity_checker_version="old",
    )
    newer = GlobalCharacterImage(
        image_path="output/generated_images/pending_review/multi_new.webp",
        quality_status="pass",
        identity_status="reject",
        quality_checker_version="old",
        identity_checker_version="old",
        identity_reasons='["weak_print_gallery"]',
    )
    character.images.extend([older, newer])
    character.review = GlobalCharacterReview(review_status="pending", rating_stage="primary")
    db.add(character)
    db.commit()
    db.refresh(character)

    rows = PendingReviewInspectionService(db).candidates(limit=50)
    assert len(rows) == 1
    selected_character, selected_image = rows[0]
    assert selected_character.id == character.id
    assert selected_image.id == newer.id
    assert selected_image.id == max(image.id for image in character.images)


def test_repair_loop_reinspects_after_regeneration(db: Session, monkeypatch) -> None:
    character = add_character(db, tag="reinspect_loop", review_status="pending")
    service = PendingReviewInspectionService(db)
    first = character.images[0]
    first.quality_status = "pass"
    first.identity_status = "reject"
    first.identity_reasons = '["weak_print_gallery"]'
    first.quality_checker_version = QUALITY_CHECKER_VERSION
    first.identity_checker_version = IDENTITY_CHECKER_VERSION
    db.commit()

    second = GlobalCharacterImage(
        global_character_id=character.id,
        image_path="output/generated_images/pending_review/reinspect_loop_2.webp",
        quality_status="pass",
        identity_status="reject",
        identity_reasons='["weak_print_gallery"]',
        quality_checker_version=QUALITY_CHECKER_VERSION,
        identity_checker_version=IDENTITY_CHECKER_VERSION,
    )
    db.add(second)
    db.commit()
    db.refresh(second)

    calls = {"regen": 0, "inspect": 0}

    def fake_inspect(character_obj, image_obj):
        calls["inspect"] += 1
        return image_obj

    def fake_regen(character_obj, **kwargs):
        calls["regen"] += 1
        from app.services.v2_generation_pipeline import V2PipelineResult

        if calls["regen"] == 1:
            return (
                V2PipelineResult(character_obj.id, "generation_failed", 1, second.id),
                1,
            )
        third = GlobalCharacterImage(
            global_character_id=character_obj.id,
            image_path="output/generated_images/pending_review/reinspect_loop_3.webp",
            quality_status="pass",
            identity_status="pass",
            identity_reasons="[]",
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_checker_version=IDENTITY_CHECKER_VERSION,
        )
        db.add(third)
        db.commit()
        db.refresh(third)
        return V2PipelineResult(character_obj.id, "generated", 2, third.id), 1

    monkeypatch.setattr(service, "_inspect_existing", fake_inspect)
    monkeypatch.setattr(service, "_regenerate_capped", fake_regen)

    summary = PendingInspectionSummary(requested_limit=1)
    final_image, context, auto_zero = service._repair_with_stages(
        character,
        first,
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert calls["regen"] >= 2
    assert context.reinspection_completed >= 1
    assert context.regeneration_completed >= 2
    assert STAGE_SEMANTIC_GALLERY in context.attempted_stages
    assert auto_zero is False or context.final_action in {"pass", "0성"}
    assert final_image.id >= second.id


def test_identity_persistent_failure_auto_zeros_without_semantic(db: Session, monkeypatch) -> None:
    character = add_character(db, tag="identity_zero", review_status="pending")
    character.gender = "1boy"
    image = character.images[0]
    image.quality_status = "pass"
    image.identity_status = "warning"
    image.identity_reasons = '["hair_color_mismatch"]'
    image.quality_checker_version = QUALITY_CHECKER_VERSION
    image.identity_checker_version = IDENTITY_CHECKER_VERSION
    db.commit()

    def fake_regen(character_obj, **kwargs):
        from app.services.v2_generation_pipeline import V2PipelineResult

        nxt = GlobalCharacterImage(
            global_character_id=character_obj.id,
            image_path=f"output/generated_images/pending_review/identity_zero_{kwargs.get('repair_stage')}.webp",
            quality_status="pass",
            identity_status="warning",
            identity_reasons='["hair_color_mismatch","character_tag_low_confidence"]',
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_checker_version=IDENTITY_CHECKER_VERSION,
        )
        db.add(nxt)
        db.commit()
        db.refresh(nxt)
        return V2PipelineResult(character_obj.id, "generation_failed", 1, nxt.id), 1

    service = PendingReviewInspectionService(db)
    monkeypatch.setattr(service, "_regenerate_capped", fake_regen)
    monkeypatch.setattr(service, "_inspect_existing", lambda c, i: i)

    summary = PendingInspectionSummary(requested_limit=1)
    _final, context, auto_zero = service._repair_with_stages(
        character,
        image,
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert auto_zero is True
    assert context.final_action == "0성"
    assert STAGE_IDENTITY_HAIR in context.attempted_stages
    assert STAGE_SEMANTIC_OUTFIT not in context.attempted_stages
    assert STAGE_SEMANTIC_GALLERY not in context.attempted_stages
