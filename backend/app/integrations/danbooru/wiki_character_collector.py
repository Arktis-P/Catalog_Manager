from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.integrations.danbooru.client import DanbooruClient
from app.integrations.danbooru.wiki_dtext import (
    WIKI_LINK_RE,
    extract_wiki_links,
    is_list_of_characters_page,
    normalize_wiki_title,
    resolve_wiki_tag_candidates,
)

CollectProgressCallback = Callable[[dict[str, object]], None]

LIST_PAGE_TITLE_PATTERNS = (
    "list_of_{series_tag}_characters",
    "list_of_{series_tag}_character",
    "list_of_{series_tag}s_characters",
)

MAX_WIKI_SEARCH_RESULTS = 10
MAX_WIKI_PARSE_PAGES = 20
MAX_LINKS_PER_WIKI_PAGE = 500


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

    def _discover_list_page_titles(
        self,
        series_tag: str,
        *,
        progress_callback: CollectProgressCallback | None = None,
    ) -> list[str]:
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
        unique_candidates: list[str] = []
        for title in candidates:
            normalized_title = normalize_wiki_title(title)
            if normalized_title in seen:
                continue
            seen.add(normalized_title)
            unique_candidates.append(normalized_title)

        total_checks = len(unique_candidates)
        for index, normalized_title in enumerate(unique_candidates, start=1):
            self._emit(
                progress_callback,
                phase="discovering_wiki",
                message=(
                    f"list 페이지 검색 {index}/{total_checks} · {series_tag} · {normalized_title}"
                ),
                current=index,
                total=total_checks,
                discovered=0,
            )
            if self._fetch_wiki_body(normalized_title):
                found.append(normalized_title)

        search_patterns: list[str] = []
        if compact:
            search_patterns.append(f"list_of*{compact}*characters*")
        elif "/" not in normalized_series:
            search_patterns.append(f"list_of*{normalized_series}*characters*")

        search_titles: list[str] = []
        for pattern in search_patterns:
            for page in self.client.search_wiki_pages(
                title_matches=pattern,
                limit=MAX_WIKI_SEARCH_RESULTS,
            ):
                title = str(page.get("title") or "").strip()
                if not title or not is_list_of_characters_page(title):
                    continue
                normalized_title = normalize_wiki_title(title)
                if normalized_title in seen:
                    continue
                seen.add(normalized_title)
                search_titles.append(normalized_title)

        search_total = len(search_titles)
        for index, normalized_title in enumerate(search_titles, start=1):
            self._emit(
                progress_callback,
                phase="discovering_wiki",
                message=(
                    f"list 검색 결과 확인 {index}/{search_total} · {series_tag} · {normalized_title}"
                ),
                current=index,
                total=max(search_total, 1),
                discovered=0,
            )
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

    def _resolve_character_tag(self, raw_link: str) -> str | None:
        for candidate in resolve_wiki_tag_candidates(raw_link):
            if self._get_tag_category(candidate) == DanbooruClient.CATEGORY_CHARACTER:
                return candidate
        return None

    def _extract_raw_wiki_links(self, body: str) -> list[str]:
        raw_links: list[str] = []
        for match in WIKI_LINK_RE.finditer(body):
            raw = match.group(1).strip()
            if raw and not raw.startswith("!") and not raw.startswith("#"):
                raw_links.append(raw)
        return raw_links

    def _classify_raw_wiki_links(
        self,
        result: WikiDiscoveryResult,
        raw_links: list[str],
        *,
        series_tag: str,
        wiki_title: str,
        from_list_page: bool,
    ) -> None:
        normalized_series = normalize_wiki_title(series_tag)
        for raw in raw_links[:MAX_LINKS_PER_WIKI_PAGE]:
            character_tag = self._resolve_character_tag(raw)
            if character_tag:
                self._add_character(
                    result,
                    character_tag,
                    from_list_page=from_list_page,
                    wiki_title=wiki_title,
                )
                continue

            for candidate in resolve_wiki_tag_candidates(raw):
                category = self._get_tag_category(candidate)
                if category == DanbooruClient.CATEGORY_COPYRIGHT and candidate != normalized_series:
                    if candidate not in result.sub_series_tags:
                        result.sub_series_tags.append(candidate)
                    break

    def _parse_wiki_page(
        self,
        result: WikiDiscoveryResult,
        *,
        series_tag: str,
        wiki_title: str,
        from_list_page: bool,
        visited: set[str],
    ) -> str | None:
        normalized_title = normalize_wiki_title(wiki_title)
        if normalized_title in visited:
            return None
        visited.add(normalized_title)
        result.visited_wiki_titles.append(normalized_title)

        body = self._fetch_wiki_body(normalized_title)
        if not body:
            return None

        self._classify_raw_wiki_links(
            result,
            self._extract_raw_wiki_links(body),
            series_tag=series_tag,
            wiki_title=normalized_title,
            from_list_page=from_list_page,
        )

        if from_list_page or is_list_of_characters_page(normalized_title):
            if normalized_title not in result.list_page_titles:
                result.list_page_titles.append(normalized_title)
        return body

    def discover(
        self,
        series_tag: str,
        *,
        progress_callback: CollectProgressCallback | None = None,
    ) -> WikiDiscoveryResult:
        result = WikiDiscoveryResult(series_tag=series_tag)
        visited: set[str] = set()
        normalized_series = normalize_wiki_title(series_tag)

        list_titles = self._discover_list_page_titles(series_tag, progress_callback=progress_callback)
        work_queue: list[tuple[str, bool]] = [(title, True) for title in list_titles[:MAX_WIKI_PARSE_PAGES]]
        if not any(title == normalized_series for title, _ in work_queue):
            work_queue.append((normalized_series, False))

        processed = 0
        queue_index = 0
        while queue_index < len(work_queue):
            if queue_index >= MAX_WIKI_PARSE_PAGES:
                break
            wiki_title, from_list_page = work_queue[queue_index]
            queue_index += 1
            processed += 1
            total_pages = len(work_queue)

            self._emit(
                progress_callback,
                phase="discovering_wiki",
                message=f"위키 파싱 {processed}/{total_pages} · {series_tag} · {wiki_title}",
                current=processed,
                total=total_pages,
                discovered=len(result.characters),
            )

            body = self._parse_wiki_page(
                result,
                series_tag=series_tag,
                wiki_title=wiki_title,
                from_list_page=from_list_page,
                visited=visited,
            )

            if wiki_title == normalized_series and body:
                for link in extract_wiki_links(body):
                    if len(work_queue) >= MAX_WIKI_PARSE_PAGES:
                        break
                    if not is_list_of_characters_page(link):
                        continue
                    linked_title = normalize_wiki_title(link)
                    if linked_title in visited:
                        continue
                    if any(existing_title == linked_title for existing_title, _ in work_queue):
                        continue
                    work_queue.append((linked_title, True))

        if result.characters:
            result.sub_series_tags = []

        self._emit(
            progress_callback,
            phase="discovering_wiki",
            message=(
                f"위키 발견 완료 · 페이지 {len(result.visited_wiki_titles)} · "
                f"캐릭터 {len(result.characters)} · 하위 시리즈 {len(result.sub_series_tags)}"
            ),
            current=len(result.visited_wiki_titles),
            total=max(len(result.visited_wiki_titles), 1),
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
