from __future__ import annotations

from dataclasses import dataclass

from app.integrations.danbooru.client import DanbooruClient
from app.integrations.danbooru.series_collector import tag_to_display_name


@dataclass(frozen=True)
class CharacterTagRow:
    character_tag: str
    display_name: str
    post_count: int


class CharacterCatalogCollector:
    """Lists Danbooru character-category tags ordered by post_count, page by page.

    Kept intentionally simple (mirrors SeriesTagCollector): the caller drives
    pagination so it can checkpoint/pause/cancel between pages.
    """

    PAGE_LIMIT = 1000

    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()

    def collect_page(self, *, page: int, min_post_count: int) -> tuple[list[CharacterTagRow], bool]:
        """Returns (rows on this page meeting the threshold, has_more_pages)."""
        tags = self.client.list_character_tags(page=page, limit=self.PAGE_LIMIT)
        if not tags:
            return [], False

        rows: list[CharacterTagRow] = []
        below_threshold = False
        for tag in tags:
            name = str(tag.get("name") or "").strip()
            post_count = int(tag.get("post_count") or 0)
            if not name:
                continue
            if post_count < min_post_count:
                # Danbooru returns tags ordered by count desc, so once we drop
                # below the threshold everything after it will be too.
                below_threshold = True
                break
            rows.append(CharacterTagRow(character_tag=name, display_name=tag_to_display_name(name), post_count=post_count))

        has_more = len(tags) >= self.PAGE_LIMIT and not below_threshold
        return rows, has_more
