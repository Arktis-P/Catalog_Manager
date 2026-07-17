from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.services.generation_prompt_builder import GenerationPromptConfig, build_full_prompt_v2
from app.services.prompt_service import (
    build_v2_base_prompt,
    refresh_global_character_base_prompt,
)


def test_v2_base_prompt_uses_name_primary_hair_and_multicolor_candidates() -> None:
    assert (
        build_v2_base_prompt(
            character_tag="hakurei_reimu",
            primary_hair_color="brown_hair",
            multicolor_tags=["two-tone_hair", "gradient_hair"],
        )
        == "1.2::hakurei reimu::, brown hair, two-tone hair, gradient hair"
    )


def test_v2_base_prompt_adds_space_before_closing_weight_for_numeric_name() -> None:
    assert (
        build_v2_base_prompt(
            character_tag="android_18",
            primary_hair_color="blonde_hair",
            multicolor_tags=[],
        )
        == "1.2::android 18 ::, blonde hair"
    )


def test_v2_base_prompt_handles_missing_primary_hair_and_multiple_underscores() -> None:
    assert (
        build_v2_base_prompt(
            character_tag="foo__bar_baz",
            primary_hair_color=None,
            multicolor_tags=[],
        )
        == "1.2::foo  bar baz::"
    )


def test_refresh_global_character_base_prompt_uses_only_prompt_candidate_multicolor() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        character = GlobalCharacter(
            character_tag="android_18",
            display_name="Android 18",
            post_count=100,
            primary_hair_color="blonde_hair",
        )
        character.appearance_relevances.extend(
            [
                CharacterAppearanceTagRelevance(
                    tag="gradient_hair",
                    tag_category="multicolor",
                    cooccurrence_count=30,
                    character_post_count=100,
                    relevance_score=0.30,
                    is_prompt_candidate=True,
                ),
                CharacterAppearanceTagRelevance(
                    tag="blue_eyes",
                    tag_category="eye_color",
                    cooccurrence_count=80,
                    character_post_count=100,
                    relevance_score=0.80,
                    is_prompt_candidate=True,
                ),
                CharacterAppearanceTagRelevance(
                    tag="two-tone_hair",
                    tag_category="multicolor",
                    cooccurrence_count=90,
                    character_post_count=100,
                    relevance_score=0.90,
                    is_prompt_candidate=False,
                ),
            ]
        )
        db.add(character)
        db.flush()

        assert (
            refresh_global_character_base_prompt(db, character)
            == "1.2::android 18 ::, blonde hair, gradient hair"
        )
        assert character.base_prompt == "1.2::android 18 ::, blonde hair, gradient hair"


def test_refresh_global_character_base_prompt_respects_overwrite_flag() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        character = GlobalCharacter(
            character_tag="hakurei_reimu",
            display_name="Hakurei Reimu",
            post_count=100,
            primary_hair_color="brown_hair",
            base_prompt="manual prompt",
        )
        db.add(character)
        db.flush()

        assert refresh_global_character_base_prompt(db, character) == "manual prompt"
        assert character.base_prompt == "manual prompt"

        assert refresh_global_character_base_prompt(db, character, overwrite=True) == (
            "1.2::hakurei reimu::, brown hair"
        )
        assert character.previous_base_prompt == "manual prompt"


def test_build_full_prompt_v2_uses_base_prompt_with_existing_config_pattern() -> None:
    character = GlobalCharacter(
        character_tag="hakurei_reimu",
        display_name="Hakurei Reimu",
        post_count=100,
        gender="1girl",
        base_prompt="1.2::hakurei reimu::, brown hair",
    )
    config = GenerationPromptConfig(
        prefix="best quality, {gender}",
        suffix="solo, {portrait}",
        negative_prompt="bad anatomy",
    )

    prompt, negative_prompt = build_full_prompt_v2(character, prompt_config=config)

    assert prompt == "best quality, 1girl,\n\n1.2::hakurei reimu::, brown hair,\n\nsolo, portrait"
    assert negative_prompt == "bad anatomy"
