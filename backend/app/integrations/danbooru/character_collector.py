from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient

CollectProgressCallback = Callable[[dict[str, object]], None]


@dataclass
class CharacterCandidate:
    character_tag: str
    post_count: int
    from_posts: bool = False
    from_pattern: bool = False
    from_pybooru: bool = True


def tag_to_display_name(character_tag: str) -> str:
    name = character_tag.replace("_", " ")
    name = re.sub(r"\(([^)]+)\)", r" (\1)", name)
    return name.strip().title()


class CharacterCollector:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()

    def _emit(self, callback: CollectProgressCallback | None, **payload: object) -> None:
        if callback:
            callback(payload)

    def discover_character_tags(
        self,
        series_tag: str,
        *,
        max_candidates: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> dict[str, CharacterCandidate]:
        candidates: dict[str, CharacterCandidate] = {}

        self._emit(
            progress_callback,
            phase="discovering",
            message="pybooru로 character tag 패턴 검색 중...",
            current=0,
            total=0,
        )

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
                    self._emit(
                        progress_callback,
                        phase="discovering",
                        message=f"패턴 검색 완료: {len(candidates)}개 후보",
                        current=len(candidates),
                        total=len(candidates),
                        discovered=len(candidates),
                    )
                    return candidates
            self._emit(
                progress_callback,
                phase="discovering",
                message=f"패턴 검색 page {page}: {len(candidates)}개 후보",
                current=len(candidates),
                total=0,
                discovered=len(candidates),
            )
            if len(tags) < 1000:
                break

        self._emit(
            progress_callback,
            phase="discovering",
            message="pybooru post 목록에서 character tag 보완 중...",
            current=len(candidates),
            total=0,
            discovered=len(candidates),
        )

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
            if tag_name in candidates:
                candidates[tag_name].from_posts = True

        pending_post_tags = [tag_name for tag_name in seen_in_posts if tag_name not in candidates]
        for index, tag_name in enumerate(pending_post_tags, start=1):
            if max_candidates and len(candidates) >= max_candidates:
                break
            tag_info = self.client.get_tag(tag_name)
            if not tag_info or int(tag_info.get("category") or 0) != DanbooruClient.CATEGORY_CHARACTER:
                continue
            candidates[tag_name] = CharacterCandidate(
                character_tag=tag_name,
                post_count=0,
                from_posts=True,
            )
            if index == 1 or index % 25 == 0 or index == len(pending_post_tags):
                self._emit(
                    progress_callback,
                    phase="discovering",
                    message=f"post tag 검증 {index}/{len(pending_post_tags)} · 후보 {len(candidates)}개",
                    current=len(candidates),
                    total=0,
                    discovered=len(candidates),
                )

        self._emit(
            progress_callback,
            phase="discovering",
            message=f"발견 완료: 고유 character tag {len(candidates)}개",
            current=len(candidates),
            total=len(candidates),
            discovered=len(candidates),
        )
        return candidates

    def enrich_post_counts(
        self,
        series_tag: str,
        candidates: dict[str, CharacterCandidate],
        *,
        progress_label: str | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> None:
        total = len(candidates)
        self._emit(
            progress_callback,
            phase="counting",
            message="시리즈+캐릭터 조합 post_count 조회 중...",
            current=0,
            total=total,
        )
        for index, candidate in enumerate(candidates.values(), start=1):
            candidate.post_count = self.client.count_posts(
                DanbooruClient.build_search_tags(candidate.character_tag, series_tag)
            )
            if progress_label and (index == 1 or index % 25 == 0 or index == total):
                print(f"[INFO] {progress_label}: counted {index}/{total}")
            self._emit(
                progress_callback,
                phase="counting",
                message=f"post_count 조회 {index}/{total}",
                current=index,
                total=total,
            )

    def collect_for_series(
        self,
        series_tag: str,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> list[CharacterCandidate]:
        candidates = self.discover_character_tags(
            series_tag,
            max_candidates=max_characters,
            progress_callback=progress_callback,
        )
        if max_characters is not None:
            trimmed: dict[str, CharacterCandidate] = {}
            for name in sorted(candidates.keys())[:max_characters]:
                trimmed[name] = candidates[name]
            candidates = trimmed
        self.enrich_post_counts(
            series_tag,
            candidates,
            progress_label=series_tag,
            progress_callback=progress_callback,
        )
        return [
            candidate
            for candidate in candidates.values()
            if candidate.post_count > 0
        ]
