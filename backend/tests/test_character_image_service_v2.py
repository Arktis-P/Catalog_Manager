from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all relationships before mapper configuration
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.services import character_image_service
from app.services.character_image_service import (
    apply_provisional_status,
    is_provisional_eligible,
    run_v2_quality_identity_checks,
)
from app.services.identity_checker import IdentityCheckResult


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


def make_character(db: Session, tag: str = "hakurei_reimu") -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=100,
        gender="1girl",
        primary_hair_color="black_hair",
        base_prompt=f"1.2::{tag.replace('_', ' ')}::, black hair",
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def make_image(db: Session, character: GlobalCharacter, **overrides) -> GlobalCharacterImage:
    values = {"image_path": "unused.png"}
    values.update(overrides)
    image = GlobalCharacterImage(global_character_id=character.id, **values)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@pytest.mark.parametrize(
    ("quality_status", "identity_status", "expected"),
    [
        ("pass", "pass", True),
        ("pass", "warning", True),
        ("warning", "pass", True),
        ("warning", "warning", True),
        ("reject", "pass", False),
        ("pass", "reject", False),
        ("reject", "reject", False),
        ("warning", None, False),
        (None, "pass", False),
    ],
)
def test_is_provisional_eligible_covers_all_combinations(
    quality_status: str | None, identity_status: str | None, expected: bool
) -> None:
    assert is_provisional_eligible(quality_status, identity_status) is expected


def test_apply_provisional_status_registers_and_replaces_previous(db: Session) -> None:
    character = make_character(db)
    first = make_image(
        db, character, image_path="first.png", quality_status="pass", identity_status="pass"
    )
    apply_provisional_status(db, first, character)
    db.flush()
    assert first.is_provisional is True

    second = make_image(
        db, character, image_path="second.png", quality_status="warning", identity_status="warning"
    )
    apply_provisional_status(db, second, character)
    db.flush()

    db.refresh(first)
    db.refresh(second)
    assert second.is_provisional is True
    assert first.is_provisional is False


def test_apply_provisional_status_ineligible_combo_does_not_register(db: Session) -> None:
    character = make_character(db)
    image = make_image(
        db, character, image_path="rejected.png", quality_status="pass", identity_status="reject"
    )
    apply_provisional_status(db, image, character)
    db.flush()
    assert image.is_provisional is False


def _passing_quality_image(tmp_path: Path) -> Path:
    width, height = 560, 760
    image = Image.new("RGB", (width, height), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((165, 145, 235, 215), fill=(30, 30, 30))
    draw.ellipse((325, 145, 395, 215), fill=(30, 30, 30))
    hand_box = (int(width * 0.08), int(height * 0.52), int(width * 0.92), int(height * 0.96))
    draw.rectangle(hand_box, fill=(10, 10, 10))
    path = tmp_path / "generated.png"
    image.save(path)
    return path


def test_run_v2_quality_identity_checks_saves_results_and_registers_provisional(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(character_image_service.settings, "project_root", tmp_path)
    _passing_quality_image(tmp_path)

    character = make_character(db)
    make_character(db, tag="kirisame_marisa")
    image = make_image(db, character, image_path="generated.png")

    identity_kwargs = {}

    def fake_check_identity(*args, **kwargs):
        identity_kwargs.update(kwargs)
        return IdentityCheckResult(
            status="pass",
            character_confidence=0.9,
            hair_color_confidence=0.8,
            conflicting_character_tag=None,
            conflicting_character_confidence=None,
            reasons=["character_tag_confident"],
            suggested_multicolor_tags=[],
        )

    monkeypatch.setattr(character_image_service, "check_identity", fake_check_identity)

    result = run_v2_quality_identity_checks(db, image, character)

    assert result.quality_status == "pass"
    assert result.quality_checker_version == "v2.0"
    assert result.identity_status == "pass"
    assert result.identity_checker_version == "v2.0"
    assert result.character_confidence == 0.9
    assert result.is_provisional is True
    assert "known_character_tags" not in identity_kwargs


def test_run_v2_quality_identity_checks_skips_identity_when_quality_rejected(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(character_image_service.settings, "project_root", tmp_path)
    path = tmp_path / "blank.png"
    Image.new("RGB", (560, 760), (0, 0, 0)).save(path)

    character = make_character(db)
    image = make_image(db, character, image_path="blank.png")

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(character_image_service, "check_identity", fail_if_called)

    result = run_v2_quality_identity_checks(db, image, character)

    assert result.quality_status == "reject"
    assert result.identity_status is None
    assert called is False
    assert result.is_provisional is False
