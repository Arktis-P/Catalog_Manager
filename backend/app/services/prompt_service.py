from __future__ import annotations

from app.models.character import Character

MULTI_COLOR_PROMPT_TAGS = frozenset(
    {
        "red_streaks",
        "orange_streaks",
        "blonde_streaks",
        "green_streaks",
        "aqua_streaks",
        "blue_streaks",
        "black_streaks",
        "grey_streaks",
        "white_streaks",
        "brown_streaks",
        "gradient_hair",
        "colored_inner_hair",
        "multicolored_hair",
    }
)


def tag_to_prompt_text(tag: str) -> str:
    return tag.strip().replace("_", " ")


def character_tag_to_prompt_name(character_tag: str) -> str:
    return character_tag.strip().replace("_", " ")


def _primary_hair_color(hair_color: str | None) -> str | None:
    if not hair_color:
        return None
    primary = hair_color.split(",")[0].strip()
    return primary or None


def _multi_color_prompt_parts(multi_color_hair: str | None) -> list[str]:
    if not multi_color_hair:
        return []

    parts: list[str] = []
    for raw_tag in multi_color_hair.split(","):
        tag = raw_tag.strip()
        if not tag or tag == "streaked_hair":
            continue
        if tag in MULTI_COLOR_PROMPT_TAGS:
            parts.append(tag_to_prompt_text(tag))
    return parts


def build_generation_prompt(character: Character) -> str | None:
    primary = _primary_hair_color(character.hair_color)
    if not primary:
        return None

    prompt_parts = [tag_to_prompt_text(primary)]
    prompt_parts.extend(_multi_color_prompt_parts(character.multi_color_hair))

    inner = ", ".join(prompt_parts)
    name = character_tag_to_prompt_name(character.character_tag)
    return f"{{{{{name}, [[{inner}]]}}}}"


def mask_appearance_for_catalog(character: Character) -> dict[str, str | None]:
    if not character.appearance_confirmed:
        return {
            "multi_color_hair": None,
            "hair_color": None,
            "hair_shape": None,
            "eye_color": None,
            "feature_tags": None,
            "generation_prompt": None,
        }

    return {
        "multi_color_hair": character.multi_color_hair,
        "hair_color": character.hair_color,
        "hair_shape": character.hair_shape,
        "eye_color": character.eye_color,
        "feature_tags": character.feature_tags,
        "generation_prompt": character.generation_prompt,
    }
