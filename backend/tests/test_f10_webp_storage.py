from __future__ import annotations

from datetime import datetime
from io import BytesIO
from random import Random

import pytest
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app import config
from app.database import Base
from app.models.character import Character
from app.models.generation_job import GenerationJob
from app.models.global_character import GlobalCharacter
from app.models.global_character_generation_job import GlobalCharacterGenerationJob
from app.models.setting import Setting
from app.models.series import Series
from app.routers import media
from app.services.generation_service import GenerationService
from app.services.settings_service import SettingsService


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
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(config.settings, "output_dir", tmp_path / "output")


@pytest.fixture()
def png_bytes() -> bytes:
    image = PILImage.new("RGB", (128, 128))
    pixels = image.load()
    rng = Random(123456789)
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_default_generation_storage_converts_png_bytes_to_webp(db, png_bytes) -> None:
    character = GlobalCharacter(character_tag="test_character", display_name="Test Character")
    db.add(character)
    db.commit()
    db.refresh(character)
    job = GlobalCharacterGenerationJob(global_character_id=character.id, prompt="", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    image = GenerationService(db).import_generated_image_global(
        character=character,
        generation_job=job,
        image_bytes=png_bytes,
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        skip_checks=True,
    )

    path = config.settings.project_root / image.image_path
    assert path.suffix == ".webp"
    assert image.image_path.endswith(".webp")
    assert job.output_path == image.image_path
    assert path.stat().st_size < len(png_bytes)
    with PILImage.open(path) as stored:
        assert stored.format == "WEBP"
        assert stored.size == (128, 128)


def test_png_generation_format_preserves_legacy_storage(db, png_bytes) -> None:
    SettingsService(db).set_generation_image_format("png")
    series = Series(series_tag="test_series", display_name="Test Series")
    db.add(series)
    db.commit()
    db.refresh(series)
    character = Character(
        series_id=series.id,
        character_tag="test_character",
        display_name="Test Character",
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    job = GenerationJob(character_id=character.id, prompt="", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    image = GenerationService(db).import_generated_image(
        character=character,
        generation_job=job,
        image_bytes=png_bytes,
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        skip_checks=True,
    )

    path = config.settings.project_root / image.image_path
    assert path.suffix == ".png"
    assert path.read_bytes() == png_bytes
    assert job.output_path == image.image_path


def test_generation_webp_settings_are_public_and_clamped(db) -> None:
    service = SettingsService(db)

    assert service.get_public_settings()["generation_image_format"] == "webp"
    assert service.get_public_settings()["generation_webp_quality"] == 92
    assert service.set_generation_image_format("png") == "png"
    assert service.set_generation_image_format("gif") == "webp"
    assert service.set_generation_webp_quality(101) == 100
    assert service.set_generation_webp_quality(0) == 1

    db.merge(Setting(key="generation_webp_quality", value="not-an-int"))
    db.commit()
    assert SettingsService(db).get_generation_webp_quality() == 92


def test_thumbnail_route_accepts_webp_and_caches_webp(tmp_path, png_bytes) -> None:
    source_dir = config.settings.output_dir / "generated_images" / "pending_review"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "sample.webp"
    with PILImage.open(BytesIO(png_bytes)) as image:
        image.save(source_path, format="WEBP", quality=92, method=6)

    response = media.serve_thumbnail("pending_review", "sample.webp", size=128)

    assert response.media_type == "image/webp"
    cached_path = response.path
    assert str(cached_path).endswith("sample.webp")
    with PILImage.open(cached_path) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) <= 128
