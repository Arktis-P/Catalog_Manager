from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient

AppearanceProgressCallback = Callable[[dict[str, object]], None]

MULTI_COLOR_HAIR_PRIORITY = ("streaked_hair", "gradient_hair", "colored_inner_hair")
MULTI_COLOR_HAIR_FALLBACK = "multicolored_hair"

HAIR_COLORS = (
    "aqua_hair",
    "black_hair",
    "blonde_hair",
    "blue_hair",
    "brown_hair",
    "green_hair",
    "grey_hair",
    "orange_hair",
    "pink_hair",
    "purple_hair",
    "red_hair",
    "white_hair",
)

HAIR_LENGTH_TAGS = (
    "very_short_hair",
    "short_hair",
    "medium_hair",
    "long_hair",
    "very_long_hair",
    "absurdly_long_hair",
    "big_hair",
)

EYE_COLORS = (
    "aqua_eyes",
    "black_eyes",
    "blue_eyes",
    "brown_eyes",
    "green_eyes",
    "grey_eyes",
    "orange_eyes",
    "purple_eyes",
    "pink_eyes",
    "red_eyes",
    "white_eyes",
    "yellow_eyes",
)

HETEROCHROMIA_TAG = "heterochromia"
HETEROCHROMIA_MIN_FREQUENCY = 0.12
FEATURE_TAG_MAX = 8


@dataclass(frozen=True)
class RelatedTag:
    name: str
    frequency: float


@dataclass
class AppearanceTags:
    multi_color_hair: str | None = None
    hair_color: str | None = None
    hair_shape: str | None = None
    eye_color: str | None = None
    feature_tags: str | None = None


def _load_tag_dictionary(filename: str) -> tuple[str, ...]:
    path = settings.input_dir / "tag_dictionaries" / filename
    if not path.exists():
        return ()
    tags: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tags.append(line)
    return tuple(tags)


def load_hair_style_candidates() -> frozenset[str]:
    file_tags = set(_load_tag_dictionary("hair_shape.txt"))
    file_tags.difference_update(HAIR_LENGTH_TAGS)
    file_tags.difference_update(HAIR_COLORS)
    file_tags.difference_update(MULTI_COLOR_HAIR_PRIORITY)
    file_tags.discard(MULTI_COLOR_HAIR_FALLBACK)
    file_tags.discard("two-tone_hair")
    return frozenset(file_tags)


def load_feature_tag_candidates() -> frozenset[str]:
    file_tags = set(_load_tag_dictionary("feature_tags.txt"))
    file_tags.update({"demon_horns", "pointy_ears", "fang", "mole", "freckles"})
    return frozenset(file_tags)


def parse_related_tags(payload: object) -> list[RelatedTag]:
    if not isinstance(payload, dict):
        return []

    items = payload.get("related_tags")
    if not isinstance(items, list):
        return []

    parsed: list[RelatedTag] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag")
        if not isinstance(tag, dict):
            continue
        name = str(tag.get("name") or "").strip()
        if not name:
            continue
        try:
            frequency = float(item.get("frequency") or 0.0)
        except (TypeError, ValueError):
            frequency = 0.0
        parsed.append(RelatedTag(name=name, frequency=frequency))
    return parsed


def extract_multi_color_hair(related: list[RelatedTag]) -> str | None:
    by_name = {item.name: item.frequency for item in related}
    for tag in MULTI_COLOR_HAIR_PRIORITY:
        if tag in by_name:
            return tag
    if MULTI_COLOR_HAIR_FALLBACK in by_name:
        return MULTI_COLOR_HAIR_FALLBACK
    return None


def extract_hair_color(related: list[RelatedTag], *, limit: int = 5) -> str | None:
    allowed = set(HAIR_COLORS)
    matches = [item for item in related if item.name in allowed]
    matches.sort(key=lambda item: item.frequency, reverse=True)
    selected = matches[:limit]
    if not selected:
        return None
    return ", ".join(item.name for item in selected)


def extract_hair_shape(related: list[RelatedTag]) -> str | None:
    length_matches = [item for item in related if item.name in HAIR_LENGTH_TAGS]
    length_matches.sort(key=lambda item: item.frequency, reverse=True)

    style_candidates = load_hair_style_candidates()
    style_matches = [item for item in related if item.name in style_candidates]
    style_matches.sort(key=lambda item: item.frequency, reverse=True)

    parts: list[str] = []
    if length_matches:
        parts.append(length_matches[0].name)
    if style_matches:
        chosen_style = style_matches[0].name
        if chosen_style not in parts:
            parts.append(chosen_style)
    return ", ".join(parts) if parts else None


def extract_eye_color(related: list[RelatedTag]) -> str | None:
    by_name = {item.name: item.frequency for item in related}
    eye_matches = [item for item in related if item.name in EYE_COLORS]
    eye_matches.sort(key=lambda item: item.frequency, reverse=True)
    if not eye_matches:
        return None

    hetero_score = by_name.get(HETEROCHROMIA_TAG, 0.0)
    if hetero_score >= HETEROCHROMIA_MIN_FREQUENCY and len(eye_matches) >= 2:
        return f"{eye_matches[0].name}, {eye_matches[1].name}"
    return eye_matches[0].name


def extract_feature_tags(related: list[RelatedTag]) -> str | None:
    candidates = load_feature_tag_candidates()
    matches = [item for item in related if item.name in candidates]
    matches.sort(key=lambda item: item.frequency, reverse=True)
    if not matches:
        return None
    selected = matches[:FEATURE_TAG_MAX]
    return ", ".join(item.name for item in selected)


def extract_appearance_tags(related: list[RelatedTag]) -> AppearanceTags:
    return AppearanceTags(
        multi_color_hair=extract_multi_color_hair(related),
        hair_color=extract_hair_color(related),
        hair_shape=extract_hair_shape(related),
        eye_color=extract_eye_color(related),
        feature_tags=extract_feature_tags(related),
    )


class AppearanceExtractor:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()

    def fetch_related_tags(self, character_tag: str) -> list[RelatedTag]:
        payload = self.client.get_related_tags(character_tag, category=0)
        return parse_related_tags(payload)

    def extract_for_character(self, character_tag: str) -> AppearanceTags:
        related = self.fetch_related_tags(character_tag)
        return extract_appearance_tags(related)
