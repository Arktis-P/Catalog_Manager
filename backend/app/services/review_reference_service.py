from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient
from app.models.global_character import GlobalCharacter

MAX_REFERENCE_IMAGES = 5
FAVORITE_FALLBACK_LIMIT = 20
USABLE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}

_POST_REFERENCE_RE = re.compile(
    r"(?P<bang>!post\s*#?\s*(?P<bang_id>\d+))"
    r"|(?P<post_hash>\bpost\s*#\s*(?P<post_hash_id>\d+))"
    r"|(?P<post_colon>\bpost:(?P<post_colon_id>\d+))"
    r"|(?P<post_path>/posts/(?P<post_path_id>\d+))",
    re.IGNORECASE,
)


class ReviewReferenceUpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewReferenceItem:
    post_id: int
    thumbnail_url: str
    preview_url: str
    post_url: str
    source: Literal["wiki_sample", "favorite"]


@dataclass(frozen=True)
class ReviewReferenceResult:
    character_id: int
    tag: str
    items: list[ReviewReferenceItem]


def extract_wiki_sample_post_ids(body: str | None, *, limit: int = MAX_REFERENCE_IMAGES) -> list[int]:
    """Extract explicit post references from Danbooru wiki body text in source order."""
    if not body:
        return []

    post_ids: list[int] = []
    seen: set[int] = set()
    for match in _POST_REFERENCE_RE.finditer(body):
        raw_id = (
            match.group("bang_id")
            or match.group("post_hash_id")
            or match.group("post_colon_id")
            or match.group("post_path_id")
        )
        if not raw_id:
            continue
        post_id = int(raw_id)
        if post_id in seen:
            continue
        seen.add(post_id)
        post_ids.append(post_id)
        if len(post_ids) >= limit:
            break
    return post_ids


class ReviewReferenceService:
    def __init__(self, db: Session, client: DanbooruClient | None = None):
        self.db = db
        self._client = client

    @property
    def client(self) -> DanbooruClient:
        if self._client is None:
            self._client = DanbooruClient()
        return self._client

    def get_reference_images(self, character_id: int) -> ReviewReferenceResult:
        character = self.db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
        if not character:
            raise ValueError("Character not found")

        tag = character.character_tag.strip()
        selected: list[ReviewReferenceItem] = []
        seen_post_ids: set[int] = set()
        seen_image_urls: set[str] = set()

        for post in self.fetch_wiki_sample_posts(tag):
            self._append_unique_item(
                selected,
                post,
                source="wiki_sample",
                seen_post_ids=seen_post_ids,
                seen_image_urls=seen_image_urls,
            )
            if len(selected) >= MAX_REFERENCE_IMAGES:
                return ReviewReferenceResult(character_id=character.id, tag=tag, items=selected)

        for post in self.fetch_favorite_posts(tag):
            self._append_unique_item(
                selected,
                post,
                source="favorite",
                seen_post_ids=seen_post_ids,
                seen_image_urls=seen_image_urls,
            )
            if len(selected) >= MAX_REFERENCE_IMAGES:
                break

        return ReviewReferenceResult(character_id=character.id, tag=tag, items=selected)

    def fetch_wiki_sample_posts(self, tag: str) -> list[dict]:
        try:
            wiki = self.client.get_wiki_page(tag)
            body = (wiki or {}).get("body") or (wiki or {}).get("body_dtext")
            post_ids = extract_wiki_sample_post_ids(body)
            posts: list[dict] = []
            for post_id in post_ids:
                matches = self.client.list_posts(tags=f"id:{post_id}", limit=1)
                if matches:
                    posts.append(matches[0])
            return posts
        except Exception as exc:
            raise ReviewReferenceUpstreamError(f"Failed to fetch Danbooru wiki samples: {exc}") from exc

    def fetch_favorite_posts(self, tag: str) -> list[dict]:
        try:
            return self.client.list_posts(
                tags=f"{tag} order:favcount",
                limit=FAVORITE_FALLBACK_LIMIT,
            )
        except Exception as exc:
            raise ReviewReferenceUpstreamError(f"Failed to fetch Danbooru favorite posts: {exc}") from exc

    def _append_unique_item(
        self,
        items: list[ReviewReferenceItem],
        post: dict,
        *,
        source: Literal["wiki_sample", "favorite"],
        seen_post_ids: set[int],
        seen_image_urls: set[str],
    ) -> None:
        item = self._post_to_item(post, source=source)
        if item is None:
            return
        if item.post_id in seen_post_ids:
            return
        urls = {item.thumbnail_url, item.preview_url}
        if seen_image_urls.intersection(urls):
            return
        seen_post_ids.add(item.post_id)
        seen_image_urls.update(urls)
        items.append(item)

    @staticmethod
    def _post_to_item(post: dict, *, source: Literal["wiki_sample", "favorite"]) -> ReviewReferenceItem | None:
        try:
            post_id = int(post.get("id"))
        except (TypeError, ValueError):
            return None

        if post.get("is_deleted") or post.get("is_banned"):
            return None
        file_ext = str(post.get("file_ext") or "").lower()
        if file_ext and file_ext not in USABLE_IMAGE_EXTENSIONS:
            return None

        thumbnail_url = post.get("preview_file_url")
        preview_url = post.get("large_file_url") or post.get("file_url") or post.get("preview_file_url")
        if not thumbnail_url or not preview_url:
            return None

        return ReviewReferenceItem(
            post_id=post_id,
            thumbnail_url=str(thumbnail_url),
            preview_url=str(preview_url),
            post_url=f"{settings.danbooru_base_url}/posts/{post_id}",
            source=source,
        )
