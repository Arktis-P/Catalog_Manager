from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.naia.wildcard_writer import wildcard_token_name
from app.models.character import Character
from app.services.prompt_service import NAME_WEIGHT, build_generation_prompt, tag_to_prompt_text


@dataclass
class GenerationPromptConfig:
    prefix: str
    suffix: str
    negative_prompt: str


def _read_template_file(name: str, default: str = "") -> str:
    path = settings.input_dir / "prompt_templates" / name
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8").strip()


def default_generation_prompt_config() -> GenerationPromptConfig:
    return GenerationPromptConfig(
        prefix=_read_template_file(
            "generation_prefix.txt",
            "__set_artists_4.5.2__, __set_qualityTags__,\n\n{gender},",
        ),
        suffix=_read_template_file(
            "generation_suffix.txt",
            "solo, solo focus, {portrait}, smile",
        ),
        negative_prompt=_read_template_file(
            "negative_prompt.txt",
            "lowres, bad anatomy, bad hands, text, watermark, signature, blurry",
        ),
    )


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def build_character_core(character: Character, prompt_level: int) -> str | None:
    """character는 series-scoped Character 또는 GlobalCharacter일 수 있다.
    GlobalCharacter에는 generation_prompt 캐시 필드가 없으므로 getattr로 안전하게 접근한다."""
    level = max(1, min(5, prompt_level))
    if level == 1:
        cached_prompt = getattr(character, "generation_prompt", None)
        if cached_prompt:
            return cached_prompt
        return build_generation_prompt(character)

    base = build_generation_prompt(character)
    if not base:
        return None

    if level == 2:
        return base

    name = character.character_tag.replace("_", " ")
    inner_parts: list[str] = []
    if character.hair_color:
        inner_parts.append(tag_to_prompt_text(character.hair_color.split(",")[0]))
    if character.multi_color_hair:
        for tag in _split_tags(character.multi_color_hair):
            if tag != "streaked_hair":
                inner_parts.append(tag_to_prompt_text(tag))
    if level >= 3:
        for tag in _split_tags(character.hair_shape):
            inner_parts.append(tag_to_prompt_text(tag))
        for tag in _split_tags(character.eye_color):
            inner_parts.append(tag_to_prompt_text(tag))
    if level >= 4:
        for tag in _split_tags(character.feature_tags):
            inner_parts.append(tag_to_prompt_text(tag))

    inner = ", ".join(dict.fromkeys(inner_parts))
    if not inner:
        return base
    return f"{NAME_WEIGHT}::{name}::, {inner}"


def _gender_tag(character: Character) -> str:
    gender = normalize_gender(character.gender)
    if gender in {"1girl", "1boy", "no_humans"}:
        return gender
    return "1girl"


def _apply_placeholders(template: str, *, gender: str) -> str:
    return template.replace("{gender}", gender).replace("{portrait}", "portrait")


def build_full_prompt(
    character: Character,
    *,
    prompt_level: int,
    prompt_config: GenerationPromptConfig | None = None,
    queue_id: str | None = None,
    use_wildcard: bool = False,
) -> tuple[str, str]:
    config = prompt_config or default_generation_prompt_config()
    gender = _gender_tag(character)

    if use_wildcard and queue_id:
        character_part = f"__*{wildcard_token_name(queue_id)}__"
    else:
        character_core = build_character_core(character, prompt_level)
        if not character_core:
            raise ValueError(f"{character.character_tag}: generation_prompt가 없습니다.")
        character_part = character_core

    return build_prompt_from_character_core(character_part, gender=gender, prompt_config=config)


def build_prompt_from_character_core(
    character_core: str,
    *,
    gender: str,
    prompt_config: GenerationPromptConfig | None = None,
) -> tuple[str, str]:
    config = prompt_config or default_generation_prompt_config()
    character_part = character_core.strip()
    if not character_part:
        raise ValueError("prompt가 비어 있습니다.")

    normalized_gender = normalize_gender(gender)
    if normalized_gender not in {"1girl", "1boy", "no_humans"}:
        normalized_gender = "1girl"

    prefix = _apply_placeholders(config.prefix, gender=normalized_gender).strip()
    suffix = _apply_placeholders(config.suffix, gender=normalized_gender).strip()
    sections = [section for section in (prefix, character_part, suffix) if section]
    prompt = ",\n\n".join(sections)
    return prompt, config.negative_prompt


def build_queue_manifest(
    *,
    queue_id: str,
    series_tag: str,
    series_id: int,
    prompt_level: int,
    wildcard_path: Path,
    characters: list[dict[str, object]],
    prompt_template: str,
    negative_prompt: str,
    prompt_prefix: str,
    prompt_suffix: str,
) -> dict[str, object]:
    return {
        "queue_id": queue_id,
        "series_id": series_id,
        "series_tag": series_tag,
        "prompt_level": prompt_level,
        "wildcard_path": str(wildcard_path),
        "wildcard_token": f"__*{wildcard_token_name(queue_id)}__",
        "prompt_prefix": prompt_prefix,
        "prompt_suffix": prompt_suffix,
        "prompt_template": prompt_template,
        "negative_prompt": negative_prompt,
        "character_count": len(characters),
        "characters": characters,
        "naia_note": (
            "캐릭터 와일드카드는 prompt_prefix와 prompt_suffix 사이에 위치합니다. "
            "NAIA 와일드카드 파일 변경 후 Reload가 필요할 수 있습니다."
        ),
    }


def export_queue_manifest(path: Path, manifest: dict[str, object]) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
