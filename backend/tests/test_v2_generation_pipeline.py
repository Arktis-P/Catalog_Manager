from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_generation_job import GlobalCharacterGenerationJob
from app.models.global_character_image import GlobalCharacterImage
from app.routers import generation as generation_router
from app.schemas.generation import V2RegenerateRequest
from app.services.identity_checker import IdentityCheckResult
from app.services.quality_checker import QualityCheckResult
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


@pytest.fixture()
def generated_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture(autouse=True)
def output_paths(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(config.settings, "output_dir", tmp_path / "output")


def make_character(
    db: Session,
    *,
    first_post_at=None,
    multicolor: bool = False,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag="test_character",
        display_name="Test Character",
        post_count=100,
        gender="1girl",
        primary_hair_color="black_hair",
        base_prompt=(
            "1.2::test character::, black hair, gradient hair"
            if multicolor
            else "1.2::test character::, black hair"
        ),
        first_post_at=first_post_at,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    if multicolor:
        db.add(
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="gradient_hair",
                tag_category="multicolor",
                cooccurrence_count=40,
                character_post_count=100,
                relevance_score=0.4,
                is_prompt_candidate=True,
            )
        )
        db.commit()
    return character


def identity(status: str) -> IdentityCheckResult:
    return IdentityCheckResult(
        status=status,
        character_confidence=0.9 if status != "reject" else 0.1,
        hair_color_confidence=0.8 if status != "reject" else None,
        conflicting_character_tag="other_character" if status == "reject" else None,
        conflicting_character_confidence=0.9 if status == "reject" else None,
        reasons=["conflicting_character_tag"] if status == "reject" else ["character_tag_confident"],
        suggested_multicolor_tags=[],
    )


def make_pipeline(db, generated_bytes, quality_results, identity_results):
    quality_iter = iter(quality_results)
    identity_iter = iter(identity_results)
    calls = {"generate": 0, "identity": 0}

    def generate(prompt: str, negative_prompt: str) -> bytes:
        calls["generate"] += 1
        return generated_bytes

    def check_identity(*args, **kwargs):
        calls["identity"] += 1
        return next(identity_iter)

    pipeline = V2GenerationPipeline(
        db,
        image_bytes_generator=generate,
        quality_checker=lambda path: next(quality_iter),
        identity_checker=check_identity,
        wait_between_generations=lambda: 0.0,
    )
    return pipeline, calls


PASS_QUALITY = QualityCheckResult(status="pass", score=0.9, reasons=[])
REJECT_QUALITY = QualityCheckResult(status="reject", score=0.0, reasons=["blank_image"])


def test_quality_reject_three_times_marks_generation_failed(db, generated_bytes) -> None:
    character = make_character(db)
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [REJECT_QUALITY, REJECT_QUALITY, REJECT_QUALITY],
        [],
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generation_failed"
    assert result.generation_attempts == 3
    assert calls == {"generate": 3, "identity": 0}
    assert character.total_generation_attempts == 3
    assert json.loads(character.prompt_variant_attempts) == {"initial": 3}
    assert character.last_failure_reason == "quality_reject:blank_image"


def test_quality_pass_on_third_attempt_continues_to_identity(db, generated_bytes) -> None:
    character = make_character(db)
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [REJECT_QUALITY, REJECT_QUALITY, PASS_QUALITY],
        [identity("pass")],
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generated"
    assert calls == {"generate": 3, "identity": 1}
    assert character.images[-1].is_provisional is True


def test_recent_identity_reject_marks_likely_untrained_without_regeneration(
    db, generated_bytes
) -> None:
    character = make_character(db, first_post_at=datetime(2025, 5, 1))
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [PASS_QUALITY],
        [identity("reject")],
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "likely_untrained"
    assert calls["generate"] == 1


def test_level_one_revision_success_promotes_base_prompt_and_history(db, generated_bytes) -> None:
    character = make_character(db)
    db.add_all(
        [
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="black_hair",
                tag_category="hair_color",
                cooccurrence_count=80,
                character_post_count=100,
                relevance_score=0.8,
                is_prompt_candidate=True,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="brown_hair",
                tag_category="hair_color",
                cooccurrence_count=60,
                character_post_count=100,
                relevance_score=0.6,
                is_prompt_candidate=False,
            ),
        ]
    )
    db.commit()
    old_prompt = character.base_prompt
    pipeline, _ = make_pipeline(
        db,
        generated_bytes,
        [PASS_QUALITY, PASS_QUALITY],
        [identity("reject"), identity("warning")],
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generated"
    assert character.previous_base_prompt == old_prompt
    assert character.base_prompt == "1.2::test character::, brown hair"
    assert character.primary_hair_color == "brown_hair"
    assert character.prompt_revision_level == 1
    assert character.prompt_revision_reason == "primary_hair_color:black_hair->brown_hair"


def test_level_one_quality_retries_before_advancing(db, generated_bytes) -> None:
    character = make_character(db)
    db.add_all(
        [
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="black_hair",
                tag_category="hair_color",
                cooccurrence_count=80,
                character_post_count=100,
                relevance_score=0.8,
                is_prompt_candidate=True,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="brown_hair",
                tag_category="hair_color",
                cooccurrence_count=60,
                character_post_count=100,
                relevance_score=0.6,
            ),
        ]
    )
    db.commit()
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [PASS_QUALITY, REJECT_QUALITY, REJECT_QUALITY, PASS_QUALITY],
        [identity("reject"), identity("warning")],
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generated"
    assert calls == {"generate": 4, "identity": 2}
    assert character.prompt_revision_level == 1
    assert json.loads(character.prompt_variant_attempts) == {"initial": 1, "level_1": 3}


def test_all_three_revision_levels_fail_without_feature_prompt(db, generated_bytes) -> None:
    character = make_character(db, multicolor=True)
    db.add_all(
        [
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="black_hair",
                tag_category="hair_color",
                cooccurrence_count=80,
                character_post_count=100,
                relevance_score=0.8,
                is_prompt_candidate=True,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="brown_hair",
                tag_category="hair_color",
                cooccurrence_count=60,
                character_post_count=100,
                relevance_score=0.6,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="blue_eyes",
                tag_category="eye_color",
                cooccurrence_count=70,
                character_post_count=100,
                relevance_score=0.7,
                is_prompt_candidate=True,
            ),
            CharacterAppearanceTagRelevance(
                global_character_id=character.id,
                tag="glasses",
                tag_category="feature",
                cooccurrence_count=30,
                character_post_count=100,
                relevance_score=0.3,
                is_prompt_candidate=True,
            ),
        ]
    )
    db.commit()
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [PASS_QUALITY] * 4,
        [identity("reject")] * 4,
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generation_failed"
    assert calls == {"generate": 4, "identity": 4}
    assert json.loads(character.prompt_variant_attempts) == {
        "initial": 1,
        "level_1": 1,
        "level_2": 1,
        "level_3": 1,
    }
    jobs = db.query(GlobalCharacterGenerationJob).all()
    assert all("glasses" not in job.prompt for job in jobs)
    assert character.prompt_revision_level is None


def test_manual_regenerate_api_forwards_edited_prompt_and_rejects_duplicate(
    db, monkeypatch
) -> None:
    character = make_character(db)
    captured: list[tuple[int, str | None]] = []

    def start_regeneration(character_id: int, *, base_prompt: str | None):
        captured.append((character_id, base_prompt))
        if len(captured) > 1:
            return None
        from app.services.v2_generation_job_manager import V2GenerationJobState

        return V2GenerationJobState(job_id="manual-job", character_id=character_id, total=1)

    monkeypatch.setattr(
        generation_router.v2_generation_job_manager,
        "start_regeneration",
        start_regeneration,
    )
    response = generation_router.regenerate_v2_character(
        character.id,
        V2RegenerateRequest(base_prompt="1.2::edited character::, red hair"),
        db,
    )

    assert response.job_id == "manual-job"
    assert captured == [(character.id, "1.2::edited character::, red hair")]

    with pytest.raises(generation_router.HTTPException) as exc_info:
        generation_router.regenerate_v2_character(
            character.id,
            V2RegenerateRequest(base_prompt=None),
            db,
        )
    assert exc_info.value.status_code == 409


def test_manual_regenerate_uses_and_saves_edited_prompt(db, generated_bytes) -> None:
    character = make_character(db)
    edited_prompt = "1.2::edited character::, red hair"
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [PASS_QUALITY],
        [identity("pass")],
    )

    result = pipeline.run_character(character.id, base_prompt=edited_prompt)

    assert result.generation_status == "generated"
    assert calls == {"generate": 1, "identity": 1}
    assert character.base_prompt == edited_prompt
    job = db.query(GlobalCharacterGenerationJob).one()
    assert "1.2::edited character::" in job.prompt


def test_manual_regenerate_manager_reserves_character_until_job_finishes(monkeypatch) -> None:
    from app.services.v2_generation_job_manager import V2GenerationJobManager

    manager = V2GenerationJobManager()
    monkeypatch.setattr(manager, "_dispatch_next", lambda: None)

    first = manager.start_regeneration(17, base_prompt="edited prompt")
    duplicate = manager.start_regeneration(17, base_prompt=None)

    assert first is not None
    assert duplicate is None
    assert manager.cancel(first.job_id) is True
    assert manager.start_regeneration(17, base_prompt=None) is not None


@pytest.mark.parametrize(
    ("quality_status", "identity_status", "expected"),
    [
        ("pass", "pass", True),
        ("warning", "warning", True),
        ("pass", "reject", False),
    ],
)
def test_pipeline_provisional_registration_condition(
    db, generated_bytes, quality_status, identity_status, expected
) -> None:
    character = make_character(db, first_post_at=datetime(2025, 5, 1))
    quality = QualityCheckResult(status=quality_status, score=0.7, reasons=[])
    pipeline, _ = make_pipeline(db, generated_bytes, [quality], [identity(identity_status)])

    result = pipeline.run_character(character.id)

    image = db.get(GlobalCharacterImage, result.image_id)
    assert image.is_provisional is expected


def test_async_steps_check_every_image_and_finish_after_quality_retry(
    db, generated_bytes
) -> None:
    character = make_character(db)
    pipeline, calls = make_pipeline(
        db,
        generated_bytes,
        [REJECT_QUALITY, PASS_QUALITY],
        [identity("pass")],
    )
    state = pipeline.prepare_async_character(character.id)

    first_image_id = pipeline.generate_async_attempt(state, should_cancel=lambda: False)
    first_check = pipeline.check_async_attempt(state, first_image_id)
    assert first_check.needs_generation is True
    assert db.get(GlobalCharacterImage, first_image_id).quality_status == "reject"

    second_image_id = pipeline.generate_async_attempt(state, should_cancel=lambda: False)
    second_check = pipeline.check_async_attempt(state, second_image_id)

    assert second_check.needs_generation is False
    assert second_check.result.generation_status == "generated"
    assert calls == {"generate": 2, "identity": 1}
    images = db.query(GlobalCharacterImage).order_by(GlobalCharacterImage.id).all()
    assert [image.quality_status for image in images] == ["reject", "pass"]
    assert images[-1].identity_status == "pass"
    assert images[-1].is_provisional is True
