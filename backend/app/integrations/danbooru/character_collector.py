from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient


@dataclass
class CharacterCandidate:
    character_tag: str
    post_count: int
    from_posts: bool = False
    from_pattern: bool = False


def tag_to_display_name(character_tag: str) -> str:
    name = character_tag.replace("_", " ")
    name = re.sub(r"\(([^)]+)\)", r" (\1)", name)
    return name.strip().title()


class CharacterCollector:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()

    def discover_character_tags(
        self,
        series_tag: str,
        *,
        max_candidates: int | None = None,
    ) -> dict[str, CharacterCandidate]:
        candidates: dict[str, CharacterCandidate] = {}

        for page in range(1, settings.danbooru_character_tag_pages + 1):
            tags = self.client.list_character_tags_by_pattern(series_tag, page=page, limit=1000)
            if not tags:
                break
            for tag in tags:
                name = tag.get("name", "").strip()
                if not name or int(tag.get("category") or 0) != DanbooruClient.CATEGORY_CHARACTER:
                    continue
                existing = candidates.get(name)
                if existing:
                    existing.from_pattern = True
                else:
                    candidates[name] = CharacterCandidate(
                        character_tag=name,
                        post_count=0,
                        from_pattern=True,
                    )
                if max_candidates and len(candidates) >= max_candidates:
                    return candidates
            if len(tags) < 1000:
                break

        seen_in_posts: dict[str, int] = {}
        for page in range(1, settings.danbooru_character_post_pages + 1):
            if max_candidates and len(candidates) >= max_candidates:
                break
            posts = self.client.list_posts(tags=series_tag, page=page)
            if not posts:
                break
            for post in posts:
                for tag_name in (post.get("tag_string") or "").split():
                    seen_in_posts[tag_name] = seen_in_posts.get(tag_name, 0) + 1
            if len(posts) < settings.danbooru_character_post_limit:
                break

        for tag_name in seen_in_posts:
            if max_candidates and len(candidates) >= max_candidates:
                break
            if tag_name in candidates:
                candidates[tag_name].from_posts = True
                continue
            tag_info = self.client.get_tag(tag_name)
            if not tag_info or int(tag_info.get("category") or 0) != DanbooruClient.CATEGORY_CHARACTER:
                continue
            candidates[tag_name] = CharacterCandidate(
                character_tag=tag_name,
                post_count=0,
                from_posts=True,
            )

        return candidates

    def enrich_post_counts(
        self,
        series_tag: str,
        candidates: dict[str, CharacterCandidate],
        *,
        progress_label: str | None = None,
    ) -> None:
        total = len(candidates)
        for index, candidate in enumerate(candidates.values(), start=1):
            candidate.post_count = self.client.count_posts(
                DanbooruClient.build_search_tags(candidate.character_tag, series_tag)
            )
            if progress_label and (index == 1 or index % 25 == 0 or index == total):
                print(f"[INFO] {progress_label}: counted {index}/{total}")

    def collect_for_series(
        self,
        series_tag: str,
        *,
        max_characters: int | None = None,
    ) -> list[CharacterCandidate]:
        candidates = self.discover_character_tags(series_tag)
        if max_characters is not None:
            trimmed: dict[str, CharacterCandidate] = {}
            for name in sorted(candidates.keys())[:max_characters]:
                trimmed[name] = candidates[name]
            candidates = trimmed
        self.enrich_post_counts(series_tag, candidates, progress_label=series_tag)
        return [
            candidate
            for candidate in candidates.values()
            if candidate.post_count > 0
        ]
