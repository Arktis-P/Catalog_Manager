from types import SimpleNamespace

from app.integrations.danbooru.appearance_extractor import (
    RelatedTag,
    extract_multi_color_hair,
)
from app.services.prompt_service import build_generation_prompt


def test_multi_color_hair_appends_streak_colors():
    related = [
        RelatedTag("streaked_hair", 0.4),
        RelatedTag("white_streaks", 0.3),
        RelatedTag("red_streaks", 0.2),
    ]
    assert extract_multi_color_hair(related) == "streaked_hair, white_streaks, red_streaks"


def test_generation_prompt_basic():
    character = SimpleNamespace(
        character_tag="hakurei_reimu",
        hair_color="black_hair",
        multi_color_hair=None,
    )
    assert build_generation_prompt(character) == "1.2::hakurei reimu::, black hair"


def test_generation_prompt_with_streaks():
    character = SimpleNamespace(
        character_tag="tokai_teio_(umamusume)",
        hair_color="brown_hair, white_hair",
        multi_color_hair="streaked_hair, white_streaks",
    )
    assert (
        build_generation_prompt(character)
        == "1.2::tokai teio (umamusume)::, brown hair, white streaks"
    )
