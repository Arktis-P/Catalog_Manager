from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.integrations.danbooru.client import DanbooruClient
from app.integrations.danbooru.wiki_dtext import (
    extract_wiki_links,
    is_list_of_characters_page,
    normalize_wiki_title,
)

CollectProgressCallback = Callable[[dict[str, object]], None]

LIST_PAGE_TITLE_PATTERNS = (
    "list_of_{series_tag}_characters",
    "list_of_{series_tag}_character",
    "list_of_{series_tag}s_characters",
)


@dataclass
class WikiCharacterCandidate:
    character_tag: str
    post_count: int = 0
    from_wiki: bool = False
    from_list_page: bool = False
    source_wiki_title: str | None = None


@dataclass
class WikiDiscoveryResult:
    series_tag: str
    characters: dict[str, WikiCharacterCandidate] = field(default_factory=dict)
    sub_series_tags: list[str] = field(default_factory=list)
    list_page_titles: list[str] = field(default_factory=list)
    visited_wiki_titles: list[str] = field(default_factory=list)
    skipped_sub_series: list[str] = field(default_factory=list)


class WikiCharacterCollector:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()
        self._tag_category_cache: dict[str, int | None] = {}

    def _emit(self, callback: CollectProgressCallback | None, **payload: object) -> None:
        if callback:
            callback(payload)

    def _get_tag_category(self, tag_name: str) -> int | None:
        normalized = normalize_wiki_title(tag_name)
        if normalized in self._tag_category_cache:
            return self._tag_category_cache[normalized]

        tag = self.client.get_tag(normalized)
        category = int(tag.get("category") or 0) if tag else None
        self._tag_category_cache[normalized] = category
        return category

    def _fetch_wiki_body(self, title: str) -> str | None:
        page = self.client.get_wiki_page(title)
        if not page:
            return None
        body = page.get("body")
        return body if isinstance(body, str) else None

    def _discover_list_page_titles(self, series_tag: str) -> list[str]:
        normalized_series = normalize_wiki_title(series_tag)
        candidates: list[str] = []

        for pattern in LIST_PAGE_TITLE_PATTERNS:
            candidates.append(pattern.format(series_tag=normalized_series))

        compact = re.sub(r"[^a-z0-9]+", "", normalized_series)
        if compact and compact != normalized_series:
            for pattern in LIST_PAGE_TITLE_PATTERNS:
                candidates.append(pattern.format(series_tag=compact))

        if "touhou" in normalized_series:
            candidates.append("list_of_touhou_project_characters")

        found: list[str] = []
        seen: set[str] = set()
        for title in candidates:
            normalized_title = normalize_wiki_title(title)
            if normalized_title in seen:
                continue
            seen.add(normalized_title)
            if self._fetch_wiki_body(normalized_title):
                found.append(normalized_title)

        search_patterns = (
            f"list_of*{normalized_series}*characters*",
            f"list_of*{compact}*characters*" if compact else None,
        )
        for pattern in search_patterns:
            if not pattern:
                continue
            for page in self.client.search_wiki_pages(title_matches=pattern, limit=20):
                title = str(page.get("title") or "").strip()
                if not title or not is_list_of_characters_page(title):
                    continue
                normalized_title = normalize_wiki_title(title)
                if normalized_title in seen:
                    continue
                seen.add(normalized_title)
                found.append(normalized_title)

        return found

    def _add_character(
        self,
        result: WikiDiscoveryResult,
        tag_name: str,
        *,
        from_list_page: bool,
        wiki_title: str,
    ) -> None:
        normalized = normalize_wiki_title(tag_name)
        if self._get_tag_category(normalized) != DanbooruClient.CATEGORY_CHARACTER:
            return

        existing = result.characters.get(normalized)
        if existing:
            existing.from_wiki = True
            if from_list_page:
                existing.from_list_page = True
            return

        result.characters[normalized] = WikiCharacterCandidate(
            character_tag=normalized,
            from_wiki=True,
            from_list_page=from_list_page,
            source_wiki_title=wiki_title,
        )

    def _classify_links(
        self,
        result: WikiDiscoveryResult,
        links: list[str],
        *,
        series_tag: str,
        wiki_title: str,
        from_list_page: bool,
    ) -> None:
        normalized_series = normalize_wiki_title(series_tag)
        for link in links:
            category = self._get_tag_category(link)
            if category == DanbooruClient.CATEGORY_CHARACTER:
                self._add_character(
                    result,
                    link,
                    from_list_page=from_list_page,
                    wiki_title=wiki_title,
                )
            elif category == DanbooruClient.CATEGORY_COPYRIGHT and link != normalized_series:
                if link not in result.sub_series_tags:
                    result.sub_series_tags.append(link)

    def _parse_wiki_page(
        self,
        result: WikiDiscoveryResult,
        *,
        series_tag: str,
        wiki_title: str,
        from_list_page: bool,
        visited: set[str],
    ) -> None:
        normalized_title = normalize_wiki_title(wiki_title)
        if normalized_title in visited:
            return
        visited.add(normalized_title)
        result.visited_wiki_titles.append(normalized_title)

        body = self._fetch_wiki_body(normalized_title)
        if not body:
            return

        links = extract_wiki_links(body)
        self._classify_links(
            result,
            links,
            series_tag=series_tag,
            wiki_title=normalized_title,
            from_list_page=from_list_page,
        )

        if from_list_page or is_list_of_characters_page(normalized_title):
            if normalized_title not in result.list_page_titles:
                result.list_page_titles.append(normalized_title)

    def discover(
        self,
        series_tag: str,
        *,
        progress_callback: CollectProgressCallback | None = None,
    ) -> WikiDiscoveryResult:
        result = WikiDiscoveryResult(series_tag=series_tag)
        visited: set[str] = set()

        self._emit(
            progress_callback,
            phase="discovering_wiki",
            message=f"위키 탐색: {series_tag}",
            current=0,
            total=1,
            discovered=0,
        )

        list_titles = self._discover_list_page_titles(series_tag)
        for index, title in enumerate(list_titles, start=1):
            self._parse_wiki_page(
                result,
                series_tag=series_tag,
                wiki_title=title,
                from_list_page=True,
                visited=visited,
            )
            self._emit(
                progress_callback,
                phase="discovering_wiki",
                message=f"list 페이지 파싱 {index}/{len(list_titles)} · {title}",
                current=index,
                total=max(len(list_titles), 1),
                discovered=len(result.characters),
            )

        main_wiki_titles = [normalize_wiki_title(series_tag)]
        for title in main_wiki_titles:
            self._parse_wiki_page(
                result,
                series_tag=series_tag,
                wiki_title=title,
                from_list_page=False,
                visited=visited,
            )

        main_body = self._fetch_wiki_body(normalize_wiki_title(series_tag))
        if main_body:
            for link in extract_wiki_links(main_body):
                if is_list_of_characters_page(link) and link not in visited:
                    self._parse_wiki_page(
                        result,
                        series_tag=series_tag,
                        wiki_title=link,
                        from_list_page=True,
                        visited=visited,
                    )

        if result.characters:
            result.sub_series_tags = []

        self._emit(
            progress_callback,
            phase="discovering_wiki",
            message=(
                f"위키 발견 완료 · 캐릭터 {len(result.characters)} · "
                f"하위 시리즈 {len(result.sub_series_tags)}"
            ),
            current=len(result.characters),
            total=max(len(result.characters), 1),
            discovered=len(result.characters),
        )
        return result

    def enrich_post_counts(
        self,
        series_tag: str,
        candidates: dict[str, WikiCharacterCandidate],
        *,
        progress_callback: CollectProgressCallback | None = None,
    ) -> None:
        total = len(candidates)
        for index, candidate in enumerate(candidates.values(), start=1):
            candidate.post_count = self.client.count_posts(
                DanbooruClient.build_search_tags(candidate.character_tag, series_tag)
            )
            if index == 1 or index % 25 == 0 or index == total:
                self._emit(
                    progress_callback,
                    phase="counting",
                    message=f"post_count 조회 {index}/{total}",
                    current=index,
                    total=total,
                    discovered=total,
                )
