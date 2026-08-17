from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.services.identity_checker import IDENTITY_CHECKER_VERSION
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


def _female_with_relevance(db: Session) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag="e_stage_female",
        display_name="E Stage Female",
        post_count=50,
        gender="1girl",
        primary_hair_color="blue_hair",
        base_prompt="head, blue hair",
        generation_status="generated",
    )
    character.images.append(
        GlobalCharacterImage(
            image_path="output/generated_images/pending_review/e_stage.webp",
            quality_status="pass",
            identity_status="warning",
            identity_reasons='["character_tag_low_confidence"]',
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_checker_version=IDENTITY_CHECKER_VERSION,
        )
    )
    character.review = GlobalCharacterReview(review_status="pending", rating_stage="primary")
    db.add(character)
    db.flush()
    db.add_all(
        [
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="gradient_hair",
                tag_category="multicolor",
                relevance_score=0.9,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="red_eyes",
                tag_category="eye_color",
                relevance_score=0.9,
            ),
        ]
    )
    db.commit()
    db.refresh(character)
    return character


def test_female_lowconf_does_not_run_identity_stages(db: Session, monkeypatch) -> None:
    """Artifact-cleanup mode: identity low-confidence must not spend regeneration budget."""
    character = _female_with_relevance(db)
    service = PendingReviewInspectionService(db)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("identity stages are disabled")

    monkeypatch.setattr(service, "_regenerate_capped", fail_if_called)
    monkeypatch.setattr(service, "_inspect_existing", lambda c, i: i)

    summary = PendingInspectionSummary(requested_limit=1)
    _final, context, limit_hit = service._repair_with_stages(
        character,
        character.images[0],
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert context.regeneration_requested == 0
    assert context.attempted_stages == []
    assert limit_hit is False
    assert context.final_action == "pass"


def test_swimwear_reject_still_regenerates(db: Session, monkeypatch) -> None:
    character = _female_with_relevance(db)
    image = character.images[0]
    image.identity_status = "reject"
    image.identity_reasons = '["atypical_swimwear:bikini:0.88"]'
    db.commit()

    service = PendingReviewInspectionService(db)
    calls = {"n": 0}

    def fake_regen(character_obj, **kwargs):
        from app.services.v2_generation_pipeline import V2PipelineResult

        calls["n"] += 1
        nxt = GlobalCharacterImage(
            global_character_id=character_obj.id,
            image_path="output/generated_images/pending_review/e_swim_pass.webp",
            quality_status="pass",
            identity_status="pass",
            identity_reasons="[]",
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_checker_version=IDENTITY_CHECKER_VERSION,
        )
        db.add(nxt)
        db.commit()
        db.refresh(nxt)
        return V2PipelineResult(character_obj.id, "generated", 1, nxt.id), 1

    monkeypatch.setattr(service, "_regenerate_capped", fake_regen)
    monkeypatch.setattr(service, "_inspect_existing", lambda c, i: i)

    summary = PendingInspectionSummary(requested_limit=1)
    final_image, context, limit_hit = service._repair_with_stages(
        character,
        image,
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert calls["n"] == 1
    assert context.semantic_repair_stage == "semantic_outfit"
    assert limit_hit is False
    assert context.final_action == "pass"
    assert final_image.identity_status == "pass"
