from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.naia.wildcard_writer import wildcard_token_name
from app.models.character import Character
from app.services.prompt_service import build_generation_prompt, tag_to_prompt_text


def _read_template_file(name: str, default: str = "") -> str:
    path = settings.input_dir / "prompt_templates" / name
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8").strip()


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def build_character_core(character: Character, prompt_level: int) -> str | None:
    level = max(1, min(5, prompt_level))
    if level == 1:
        if character.generation_prompt:
            return character.generation_prompt
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
    return f"{{{{{name}, [[{inner}]]}}}}"


def _gender_tag(character: Character) -> str:
    gender = normalize_gender(character.gender)
    if gender in {"1girl", "1boy", "no_humans"}:
        return gender
    return "1girl"


def build_full_prompt(
    character: Character,
    *,
    prompt_level: int,
    queue_id: str | None = None,
    use_wildcard: bool = False,
    wildcard_line_index: int | None = None,
) -> tuple[str, str]:
    negative_prompt = _read_template_file(
        "negative_prompt.txt",
        "lowres, bad anatomy, bad hands, text, watermark, signature, blurry",
    )
    artist_combo = _read_template_file("artist_combo_tags.txt")
    base_prompt = _read_template_file("base_prompt.txt")

    if use_wildcard and queue_id:
        character_part = f"__*{wildcard_token_name(queue_id)}__"
    else:
        character_core = build_character_core(character, prompt_level)
        if not character_core:
            raise ValueError(f"{character.character_tag}: generation_prompt가 없습니다.")
        character_part = character_core

    quality_prefix = "__set_qualityTags__"
    artist_prefix = "__set_artists_4.5.2__" if not artist_combo else artist_combo

    sections: list[str] = []
    if prompt_level >= 5:
        sections.append(artist_prefix)
        sections.append(quality_prefix)
        if base_prompt:
            sections.append(base_prompt)
        sections.append("backlighting, [black background, simple background], abstract background")

    sections.append(f"{_gender_tag(character)}, {character_part}, solo, solo focus, {{portrait}}")

    if prompt_level >= 5:
        sections.append("smile")

    prompt = ",\n\n".join(section for section in sections if section.strip())
    return prompt, negative_prompt


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
) -> dict[str, object]:
    return {
        "queue_id": queue_id,
        "series_id": series_id,
        "series_tag": series_tag,
        "prompt_level": prompt_level,
        "wildcard_path": str(wildcard_path),
        "wildcard_token": f"__*{wildcard_token_name(queue_id)}__",
        "prompt_template": prompt_template,
        "negative_prompt": negative_prompt,
        "character_count": len(characters),
        "characters": characters,
        "naia_note": (
            "NAIA 프롬프트에 wildcard_token을 넣고 Auto Generate를 켠 뒤 Random/Generate를 "
            "반복하면 순차 와일드카드로 캐릭터가 바뀝니다. 와일드카드 파일 변경 후 NAIA에서 "
            "Reload가 필요할 수 있습니다."
        ),
    }


def export_queue_manifest(path: Path, manifest: dict[str, object]) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
