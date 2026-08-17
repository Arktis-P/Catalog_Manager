from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.services.identity_checker import IdentityCheckResult
from app.services.inspection_repair import (
    STAGE_IDENTITY_EYE,
    STAGE_IDENTITY_HAIR,
    STAGE_IDENTITY_MULTICOLOR,
)
from app.services.v2_generation_pipeline import V2GenerationPipeline


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


def make_character(db: Session, *, base_prompt: str, hair: str, gender: str = "1girl") -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag="stage_char",
        display_name="Stage Char",
        post_count=100,
        gender=gender,
        primary_hair_color=hair,
        base_prompt=base_prompt,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def add_relevance(db: Session, character_id: int, *, category: str, tag: str, score: float, candidate: bool = True) -> None:
    db.add(
        CharacterAppearanceTagRelevance(
            global_character_id=character_id,
            tag=tag,
            tag_category=category,
            relevance_score=score,
            is_prompt_candidate=candidate,
        )
    )
    db.commit()


def warning_identity(reasons: list[str], *, suggested: list[str] | None = None) -> IdentityCheckResult:
    return IdentityCheckResult(
        status="warning",
        character_confidence=0.4,
        hair_color_confidence=0.3,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=reasons,
        suggested_multicolor_tags=suggested or [],
    )


# --- _failure_reason ---------------------------------------------------------


def test_failure_reason_warning_records_reasons() -> None:
    image = GlobalCharacterImage(image_path="x.webp", quality_status="pass", quality_reasons="[]")
    identity = warning_identity(["hair_color_mismatch"])
    reason = V2GenerationPipeline._failure_reason(image, identity)
    assert reason == "identity_warning:hair_color_mismatch"


def test_failure_reason_missing_only_when_identity_none() -> None:
    image = GlobalCharacterImage(image_path="x.webp", quality_status="pass", quality_reasons="[]")
    assert V2GenerationPipeline._failure_reason(image, None) == "identity_result_missing"


def test_failure_reason_reject_and_pass() -> None:
    image = GlobalCharacterImage(image_path="x.webp", quality_status="pass", quality_reasons="[]")
    reject = IdentityCheckResult(
        status="reject",
        character_confidence=None,
        hair_color_confidence=None,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=["weak_print_gallery"],
        suggested_multicolor_tags=[],
    )
    assert V2GenerationPipeline._failure_reason(image, reject) == "identity_reject:weak_print_gallery"
    ok = IdentityCheckResult(
        status="pass",
        character_confidence=0.9,
        hair_color_confidence=0.9,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=[],
        suggested_multicolor_tags=[],
    )
    assert V2GenerationPipeline._failure_reason(image, ok) == "identity_pass"


# --- hair stage: reinforce collected hair, never swap to alternate -----------


def test_hair_stage_reinforces_expected_hair_when_present(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair, dress", hair="blue_hair")
    add_relevance(db, character.id, category="hair_color", tag="blue_hair", score=0.9)
    # A second, weaker hair must never be chosen as an alternate substitute.
    add_relevance(db, character.id, category="hair_color", tag="pink_hair", score=0.2)

    variant = V2GenerationPipeline(db).build_stage_variant(
        character, stage=STAGE_IDENTITY_HAIR, identity=warning_identity(["hair_color_mismatch"])
    )
    assert variant is not None
    assert variant.primary_hair_color == "blue_hair"
    assert "pink hair" not in variant.base_prompt
    assert variant.revision_reason == "reinforce_hair:blue_hair"


def test_hair_stage_replaces_wrong_prompt_hair_with_collected(db: Session) -> None:
    character = make_character(db, base_prompt="head, green hair, dress", hair="green_hair")
    add_relevance(db, character.id, category="hair_color", tag="blue_hair", score=0.95)

    variant = V2GenerationPipeline(db).build_stage_variant(
        character, stage=STAGE_IDENTITY_HAIR, identity=warning_identity(["hair_color_mismatch"])
    )
    assert variant is not None
    assert variant.primary_hair_color == "blue_hair"
    assert "blue hair" in variant.base_prompt
    assert "green hair" not in variant.base_prompt


def test_hair_stage_unavailable_without_data(db: Session) -> None:
    character = make_character(db, base_prompt="head, dress", hair="")
    variant = V2GenerationPipeline(db).build_stage_variant(
        character, stage=STAGE_IDENTITY_HAIR, identity=warning_identity(["hair_color_mismatch"])
    )
    assert variant is None


# --- multicolor stage: conservative add, never remove ------------------------


def test_multicolor_stage_adds_one_collected_tag(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair", hair="blue_hair")
    variant = V2GenerationPipeline(db).build_stage_variant(
        character,
        stage=STAGE_IDENTITY_MULTICOLOR,
        identity=warning_identity(["character_tag_low_confidence"], suggested=["gradient_hair"]),
    )
    assert variant is not None
    assert "gradient hair" in variant.base_prompt
    assert "blue hair" in variant.base_prompt  # existing tag preserved
    assert variant.revision_reason == "add_multicolor:gradient_hair"


def test_multicolor_stage_unavailable_without_data(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair", hair="blue_hair")
    variant = V2GenerationPipeline(db).build_stage_variant(
        character,
        stage=STAGE_IDENTITY_MULTICOLOR,
        identity=warning_identity(["character_tag_low_confidence"]),
    )
    assert variant is None


def test_multicolor_stage_skips_already_present_tag(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair, gradient hair", hair="blue_hair")
    variant = V2GenerationPipeline(db).build_stage_variant(
        character,
        stage=STAGE_IDENTITY_MULTICOLOR,
        identity=warning_identity([], suggested=["gradient_hair"]),
    )
    assert variant is None


# --- eye stage ---------------------------------------------------------------


def test_eye_stage_adds_collected_eye(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair", hair="blue_hair")
    add_relevance(db, character.id, category="eye_color", tag="red_eyes", score=0.8)
    variant = V2GenerationPipeline(db).build_stage_variant(
        character, stage=STAGE_IDENTITY_EYE, identity=warning_identity([])
    )
    assert variant is not None
    assert "red eyes" in variant.base_prompt


def test_eye_stage_unavailable_without_data(db: Session) -> None:
    character = make_character(db, base_prompt="head, blue hair", hair="blue_hair")
    variant = V2GenerationPipeline(db).build_stage_variant(
        character, stage=STAGE_IDENTITY_EYE, identity=warning_identity([])
    )
    assert variant is None
