from __future__ import annotations

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
from app.models.global_character_image import GlobalCharacterImage
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


class FakeWikiClient:
    def get_wiki_page(self, title: str):
        return {"title": title, "body": "reference only"}


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
        wiki_client=FakeWikiClient(),
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


def test_all_four_revision_levels_fail(db, generated_bytes) -> None:
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
        [PASS_QUALITY] * 5,
        [identity("reject")] * 5,
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generation_failed"
    assert calls == {"generate": 5, "identity": 5}
    assert character.prompt_revision_level is None


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
