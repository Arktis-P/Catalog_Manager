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
from app.models.global_character import GlobalCharacter
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


@pytest.fixture(autouse=True)
def output_paths(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(config.settings, "output_dir", tmp_path / "output")


def generated_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def make_character(db: Session, *, recent: bool = False) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag="semantic_test_character",
        display_name="Semantic Test Character",
        post_count=100,
        gender="1girl",
        primary_hair_color="black_hair",
        base_prompt="1.2::semantic test character::, black hair",
        first_post_at=datetime(2025, 5, 1) if recent else None,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def semantic_reject(reason: str) -> IdentityCheckResult:
    return IdentityCheckResult(
        status="reject",
        character_confidence=0.8,
        hair_color_confidence=0.8,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=[reason],
        suggested_multicolor_tags=[],
    )


def identity_pass() -> IdentityCheckResult:
    return IdentityCheckResult(
        status="pass",
        character_confidence=0.9,
        hair_color_confidence=0.8,
        conflicting_character_tag=None,
        conflicting_character_confidence=None,
        reasons=["character_tag_confident"],
        suggested_multicolor_tags=[],
    )


PASS_QUALITY = QualityCheckResult(status="pass", score=0.9, reasons=[])


def test_recent_semantic_reject_retries_same_prompt_instead_of_likely_untrained(
    db: Session,
) -> None:
    character = make_character(db, recent=True)
    identities = iter(
        [
            semantic_reject("embedded_gallery:character_sheet"),
            semantic_reject("embedded_gallery:character_sheet"),
            semantic_reject("embedded_gallery:character_sheet"),
        ]
    )
    calls = {"generate": 0}

    def generate(_prompt: str, _negative: str) -> bytes:
        calls["generate"] += 1
        return generated_bytes()

    pipeline = V2GenerationPipeline(
        db,
        image_bytes_generator=generate,
        quality_checker=lambda _path: PASS_QUALITY,
        identity_checker=lambda *_args, **_kwargs: next(identities),
        wait_between_generations=lambda: 0.0,
    )

    result = pipeline.run_character(character.id)

    assert result.generation_status == "generation_failed"
    assert calls["generate"] == 3
    assert character.prompt_revision_level is None
    assert character.base_prompt == "1.2::semantic test character::, black hair"


def test_async_semantic_reject_retries_same_variant_then_accepts_clean_image(
    db: Session,
) -> None:
    character = make_character(db)
    identities = iter(
        [
            semantic_reject("atypical_swimwear:0.91/0.01"),
            identity_pass(),
        ]
    )
    prompts: list[str] = []

    def generate(prompt: str, _negative: str) -> bytes:
        prompts.append(prompt)
        return generated_bytes()

    pipeline = V2GenerationPipeline(
        db,
        image_bytes_generator=generate,
        quality_checker=lambda _path: PASS_QUALITY,
        identity_checker=lambda *_args, **_kwargs: next(identities),
        wait_between_generations=lambda: 0.0,
    )
    state = pipeline.prepare_async_character(character.id)

    first_id = pipeline.generate_async_attempt(state, should_cancel=lambda: False)
    first = pipeline.check_async_attempt(state, first_id)
    assert first.needs_generation is True
    assert state.revision_index == -1
    assert state.current_variant.base_prompt == state.initial_variant.base_prompt

    second_id = pipeline.generate_async_attempt(state, should_cancel=lambda: False)
    second = pipeline.check_async_attempt(state, second_id)

    assert second.needs_generation is False
    assert second.result is not None
    assert second.result.generation_status == "generated"
    assert len(prompts) == 2
    assert prompts[0] == prompts[1]
    assert character.prompt_revision_level is None
