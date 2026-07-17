from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import database
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter


@pytest.fixture()
def temp_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    old_engine = database.engine
    temp_dir = Path(__file__).parent / ".tmp_v2_schema" / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    test_engine = create_engine(
        f"sqlite:///{temp_dir / 'catalogue.db'}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database, "engine", test_engine)
    database.SessionLocal.configure(bind=test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()
        database.SessionLocal.configure(bind=old_engine)
        shutil.rmtree(temp_dir, ignore_errors=True)


def _columns(engine: Engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def test_init_db_creates_v2_schema(temp_engine: Engine) -> None:
    database.init_db()
    inspector = inspect(temp_engine)

    assert "character_appearance_tag_relevance" in inspector.get_table_names()
    assert {
        "primary_hair_color",
        "primary_hair_needs_review",
        "base_prompt",
        "previous_base_prompt",
        "prompt_revision_reason",
        "prompt_revision_level",
        "first_post_at",
        "generation_status",
        "generation_attempts",
    }.issubset(_columns(temp_engine, "global_characters"))
    assert {
        "quality_status",
        "quality_score",
        "quality_reasons",
        "quality_checked_at",
        "quality_checker_version",
        "identity_status",
        "character_confidence",
        "hair_color_confidence",
        "conflicting_character_tag",
        "conflicting_character_confidence",
        "identity_reasons",
        "suggested_multicolor_tags",
        "identity_checked_at",
        "identity_checker_version",
        "is_provisional",
    }.issubset(_columns(temp_engine, "global_character_images"))
    assert {"review_status", "rating_stage"}.issubset(_columns(temp_engine, "global_character_reviews"))


def test_legacy_schema_is_migrated_to_v2_columns(temp_engine: Engine) -> None:
    with temp_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE global_characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_tag VARCHAR(255) NOT NULL UNIQUE,
                    display_name VARCHAR(255) NOT NULL DEFAULT '',
                    post_count INTEGER NOT NULL DEFAULT 0,
                    collect_status VARCHAR(50) NOT NULL DEFAULT 'uncollected',
                    appearance_status VARCHAR(50) NOT NULL DEFAULT 'uncollected',
                    gender_status VARCHAR(50) NOT NULL DEFAULT 'uncollected',
                    series_status VARCHAR(50) NOT NULL DEFAULT 'uncollected',
                    multi_color_hair TEXT,
                    hair_color TEXT,
                    hair_shape TEXT,
                    eye_color TEXT,
                    feature_tags TEXT,
                    gender VARCHAR(50),
                    error_message TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_collected_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE global_character_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    global_character_id INTEGER NOT NULL,
                    generation_job_id INTEGER,
                    image_path VARCHAR(512) NOT NULL,
                    auto_tags TEXT,
                    auto_status VARCHAR(50),
                    hair_match BOOLEAN,
                    eye_match BOOLEAN,
                    gender_pred VARCHAR(50),
                    cover_score FLOAT,
                    is_rejected BOOLEAN NOT NULL DEFAULT 0,
                    is_cover BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE global_character_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    global_character_id INTEGER NOT NULL UNIQUE,
                    cover_image_id INTEGER,
                    gender VARCHAR(50),
                    type VARCHAR(50),
                    rating INTEGER,
                    final_prompt TEXT,
                    selected_tags TEXT,
                    review_note TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    database.init_db()

    assert "character_appearance_tag_relevance" in inspect(temp_engine).get_table_names()
    assert {"generation_status", "generation_attempts", "primary_hair_needs_review"}.issubset(
        _columns(temp_engine, "global_characters")
    )
    assert {"quality_status", "identity_status", "is_provisional"}.issubset(
        _columns(temp_engine, "global_character_images")
    )
    assert {"review_status", "rating_stage"}.issubset(_columns(temp_engine, "global_character_reviews"))


def test_appearance_relevance_crud_and_character_cascade(temp_engine: Engine) -> None:
    database.init_db()

    with Session(temp_engine) as db:
        character = GlobalCharacter(
            character_tag="hakurei_reimu",
            display_name="Hakurei Reimu",
            post_count=100,
        )
        character.appearance_relevances.append(
            CharacterAppearanceTagRelevance(
                tag="black_hair",
                tag_category="hair_color",
                cooccurrence_count=42,
                character_post_count=100,
                relevance_score=0.42,
                is_prompt_candidate=True,
                is_confirmed=True,
            )
        )
        db.add(character)
        db.commit()
        character_id = character.id

    with Session(temp_engine) as db:
        relevance = db.query(CharacterAppearanceTagRelevance).one()
        assert relevance.global_character_id == character_id
        assert relevance.tag == "black_hair"
        assert relevance.is_confirmed is True

        character = db.get(GlobalCharacter, character_id)
        assert character is not None
        db.delete(character)
        db.commit()

    with Session(temp_engine) as db:
        assert db.query(CharacterAppearanceTagRelevance).count() == 0
