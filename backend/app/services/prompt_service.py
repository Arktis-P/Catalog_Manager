from __future__ import annotations

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.models.character import Character

NAME_WEIGHT = "1.2"

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


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def build_generation_prompt(character: Character) -> str | None:
    """캐릭터의 외형 태그로부터 생성 프롬프트를 만든다.

    머리색(hair_color)이 있으면 그것을 기준으로 삼지만, 포켓몬이나 갑옷/가면
    캐릭터처럼 "머리카락" 자체가 없어 hair_color가 수집되지 않는 캐릭터도 있다.
    이런 캐릭터가 이미지 생성 대상에서 통째로 제외되지 않도록, hair_color가
    없으면 눈 색/머리 모양/특징 태그로 대체하고, 그마저도 전혀 없으면 캐릭터
    이름만으로라도 프롬프트를 생성한다(절대 None을 반환해 조용히 건너뛰지 않음).
    """
    prompt_parts: list[str] = []

    primary = _primary_hair_color(character.hair_color)
    if primary:
        prompt_parts.append(tag_to_prompt_text(primary))
        prompt_parts.extend(_multi_color_prompt_parts(character.multi_color_hair))
    else:
        prompt_parts.extend(tag_to_prompt_text(tag) for tag in _split_tags(character.hair_shape))
        prompt_parts.extend(tag_to_prompt_text(tag) for tag in _split_tags(character.eye_color))
        prompt_parts.extend(tag_to_prompt_text(tag) for tag in _split_tags(character.feature_tags))

    name = character_tag_to_prompt_name(character.character_tag)
    unique_parts = list(dict.fromkeys(prompt_parts))
    if not unique_parts:
        return f"{NAME_WEIGHT}::{name}::"

    inner = ", ".join(unique_parts)
    return f"{NAME_WEIGHT}::{name}::, {inner}"


def mask_appearance_for_catalog(character: Character) -> dict[str, str | None]:
    if not character.appearance_confirmed:
        return {
            "multi_color_hair": None,
            "hair_color": None,
            "hair_shape": None,
            "eye_color": None,
            "feature_tags": None,
            "gender": None,
            "generation_prompt": None,
        }

    return {
        "multi_color_hair": character.multi_color_hair,
        "hair_color": character.hair_color,
        "hair_shape": character.hair_shape,
        "eye_color": character.eye_color,
        "feature_tags": character.feature_tags,
        "gender": normalize_gender(character.gender),
        "generation_prompt": character.generation_prompt,
    }


def mask_appearance_for_global_catalog(character) -> dict[str, str | None]:
    """`mask_appearance_for_catalog`의 GlobalCharacter(캐릭터 목록) 버전.
    appearance_confirmed 대신 appearance_status == 'completed'로 확인 여부를 판단한다."""
    if character.appearance_status != "completed":
        return {
            "multi_color_hair": None,
            "hair_color": None,
            "hair_shape": None,
            "eye_color": None,
            "feature_tags": None,
            "gender": None,
            "generation_prompt": None,
        }

    return {
        "multi_color_hair": character.multi_color_hair,
        "hair_color": character.hair_color,
        "hair_shape": character.hair_shape,
        "eye_color": character.eye_color,
        "feature_tags": character.feature_tags,
        "gender": normalize_gender(character.gender),
        "generation_prompt": getattr(character, "generation_prompt", None),
    }
