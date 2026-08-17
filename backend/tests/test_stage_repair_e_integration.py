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
from app.services.identity_checker import IDENTITY_CHECKER_VERSION, IdentityCheckResult
from app.services.inspection_repair import (
    STAGE_IDENTITY_EYE,
    STAGE_IDENTITY_HAIR,
    STAGE_IDENTITY_MULTICOLOR,
)
from app.services.pending_review_inspection_service import (
    PendingInspectionSummary,
    PendingReviewInspectionService,
)
from app.services.quality_checker import QUALITY_CHECKER_VERSION
from app.services.v2_generation_pipeline import V2GenerationPipeline, V2PipelineResult


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
        base_prompt="1.2::e stage female::, blue hair",
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
                is_prompt_candidate=True,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="red_eyes",
                tag_category="eye_color",
                relevance_score=0.8,
                is_prompt_candidate=True,
            ),
        ]
    )
    db.commit()
    db.refresh(character)
    return character


def test_female_lowconf_runs_multicolor_then_eye_with_real_relevance(db: Session, monkeypatch) -> None:
    character = _female_with_relevance(db)
    service = PendingReviewInspectionService(db)
    prompts: list[tuple[str, str | None, str | None]] = []

    def fake_regen(character_obj, **kwargs):
        stage = kwargs.get("repair_stage")
        pipeline = V2GenerationPipeline(db)
        snap = kwargs.get("identity_snapshot")
        variant = pipeline.build_stage_variant(character_obj, stage=stage, identity=snap)
        assert variant is not None, f"stage {stage} must have collected data"
        before = character_obj.base_prompt
        pipeline.apply_variant_to_character(character_obj, variant)
        prompts.append((stage, before, character_obj.base_prompt))
        # Keep actionable low-confidence until eye stage has been applied.
        reasons = (
            '["character_tag_low_confidence"]'
            if stage != STAGE_IDENTITY_EYE
            else "[]"
        )
        status = "warning" if reasons != "[]" else "pass"
        nxt = GlobalCharacterImage(
            global_character_id=character_obj.id,
            image_path=f"output/generated_images/pending_review/e_{stage}.webp",
            quality_status="pass",
            identity_status=status,
            identity_reasons=reasons,
            quality_checker_version=QUALITY_CHECKER_VERSION,
            identity_checker_version=IDENTITY_CHECKER_VERSION,
        )
        db.add(nxt)
        db.commit()
        db.refresh(nxt)
        return V2PipelineResult(
            character_obj.id,
            "generated" if status == "pass" else "generation_failed",
            1,
            nxt.id,
        ), 1

    monkeypatch.setattr(service, "_regenerate_capped", fake_regen)
    monkeypatch.setattr(service, "_inspect_existing", lambda c, i: i)

    summary = PendingInspectionSummary(requested_limit=1)
    _final, context, auto_zero = service._repair_with_stages(
        character,
        character.images[0],
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert [stage for stage, _, _ in prompts] == [
        STAGE_IDENTITY_MULTICOLOR,
        STAGE_IDENTITY_EYE,
    ]
    assert STAGE_IDENTITY_HAIR not in context.attempted_stages
    assert "gradient hair" in (prompts[0][2] or "")
    assert "red eyes" in (prompts[1][2] or "")
    assert context.regeneration_completed == 2
    assert context.unavailable_stages == []
    assert auto_zero is False
    assert context.final_action == "pass"


def test_female_lowconf_skips_missing_multicolor_without_budget(db: Session, monkeypatch) -> None:
    character = _female_with_relevance(db)
    # Remove multicolor; keep eye only.
    db.query(CharacterAppearanceTagRelevance).filter(
        CharacterAppearanceTagRelevance.tag_category == "multicolor"
    ).delete()
    db.commit()

    service = PendingReviewInspectionService(db)
    stages: list[str] = []

    def fake_regen(character_obj, **kwargs):
        stage = kwargs["repair_stage"]
        stages.append(stage)
        pipeline = V2GenerationPipeline(db)
        variant = pipeline.build_stage_variant(
            character_obj, stage=stage, identity=kwargs.get("identity_snapshot")
        )
        assert variant is not None
        pipeline.apply_variant_to_character(character_obj, variant)
        nxt = GlobalCharacterImage(
            global_character_id=character_obj.id,
            image_path=f"output/generated_images/pending_review/e_skip_{stage}.webp",
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
    _final, context, _auto_zero = service._repair_with_stages(
        character,
        character.images[0],
        auto_regenerate=True,
        max_regenerations=2,
        cleanup_rejected=False,
        summary=summary,
    )

    assert STAGE_IDENTITY_MULTICOLOR in context.unavailable_stages
    assert stages == [STAGE_IDENTITY_EYE]
    assert context.regeneration_completed == 1
