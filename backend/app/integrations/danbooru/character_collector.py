from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient

CollectProgressCallback = Callable[[dict[str, object]], None]
TAG_BATCH_SIZE = 100


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


def character_tag_suffix(series_tag: str) -> str:
    return f"_({series_tag})"


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
        suffix = character_tag_suffix(series_tag)
        max_pattern_pages = settings.danbooru_character_tag_pages

        self._emit(
            progress_callback,
            phase="discovering_pattern",
            message=f"패턴 검색 시작: *{suffix}",
            current=0,
            total=max_pattern_pages,
            discovered=0,
        )

        for page in range(1, max_pattern_pages + 1):
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
                        phase="discovering_pattern",
                        message=f"패턴 검색 완료: {len(candidates)}개 후보",
                        current=page,
                        total=page,
                        discovered=len(candidates),
                    )
                    return candidates
            self._emit(
                progress_callback,
                phase="discovering_pattern",
                message=f"패턴 검색 {page}/{max_pattern_pages} · 후보 {len(candidates)}개",
                current=page,
                total=max_pattern_pages,
                discovered=len(candidates),
            )
            if len(tags) < 1000:
                break

        if not settings.danbooru_character_post_supplement:
            self._emit(
                progress_callback,
                phase="discovering_pattern",
                message=f"발견 완료: 패턴 검색 {len(candidates)}개 (post 보완 생략)",
                current=len(candidates),
                total=len(candidates),
                discovered=len(candidates),
            )
            return candidates

        max_post_pages = settings.danbooru_character_post_pages
        seen_in_posts: dict[str, int] = {}

        self._emit(
            progress_callback,
            phase="discovering_posts_scan",
            message=f"post 목록 스캔 시작 (최대 {max_post_pages}페이지)",
            current=0,
            total=max_post_pages,
            discovered=len(candidates),
        )

        for page in range(1, max_post_pages + 1):
            if max_candidates and len(candidates) >= max_candidates:
                break
            posts = self.client.list_posts(tags=series_tag, page=page)
            if not posts:
                break
            for post in posts:
                for tag_name in (post.get("tag_string") or "").split():
                    seen_in_posts[tag_name] = seen_in_posts.get(tag_name, 0) + 1
            self._emit(
                progress_callback,
                phase="discovering_posts_scan",
                message=f"post 스캔 {page}/{max_post_pages} · 고유 tag {len(seen_in_posts)}개",
                current=page,
                total=max_post_pages,
                discovered=len(candidates),
            )
            if len(posts) < settings.danbooru_character_post_limit:
                break

        for tag_name in seen_in_posts:
            if tag_name in candidates:
                candidates[tag_name].from_posts = True

        pending_post_tags = sorted(
            tag_name
            for tag_name in seen_in_posts
            if tag_name not in candidates and tag_name.endswith(suffix)
        )
        verify_total = len(pending_post_tags)

        self._emit(
            progress_callback,
            phase="discovering_posts_verify",
            message=(
                f"post 보완 tag 검증 {verify_total}개 "
                f"(전체 post tag {len(seen_in_posts)}개 중 suffix 일치분만)"
            ),
            current=0,
            total=verify_total,
            discovered=len(candidates),
        )

        for batch_start in range(0, verify_total, TAG_BATCH_SIZE):
            if max_candidates and len(candidates) >= max_candidates:
                break
            batch = pending_post_tags[batch_start : batch_start + TAG_BATCH_SIZE]
            tag_infos = self.client.get_tags_by_names(batch)
            for tag_info in tag_infos:
                name = tag_info.get("name", "").strip()
                if not name or int(tag_info.get("category") or 0) != DanbooruClient.CATEGORY_CHARACTER:
                    continue
                if name in candidates:
                    candidates[name].from_posts = True
                    continue
                candidates[name] = CharacterCandidate(
                    character_tag=name,
                    post_count=0,
                    from_posts=True,
                )
            checked = min(batch_start + len(batch), verify_total)
            self._emit(
                progress_callback,
                phase="discovering_posts_verify",
                message=f"post tag 검증 {checked}/{verify_total} · 후보 {len(candidates)}개",
                current=checked,
                total=verify_total,
                discovered=len(candidates),
            )

        self._emit(
            progress_callback,
            phase="discovering_pattern",
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
            message=f"post_count 조회 시작 · {total}개 (약 {max(1, int(total * settings.danbooru_request_delay / 60))}분+)",
            current=0,
            total=total,
            discovered=total,
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
                discovered=total,
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
