from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from pybooru import Danbooru
from pybooru.exceptions import PybooruHTTPError

from app.config import settings


class DanbooruAuthError(Exception):
    pass


class DanbooruClient:
    CATEGORY_CHARACTER = 4

    def __init__(
        self,
        *,
        username: str | None = None,
        api_key: str | None = None,
        request_delay: float | None = None,
    ):
        self.username = (username or settings.danbooru_username).strip()
        self.api_key = (api_key or settings.danbooru_api_key).strip()
        self.request_delay = request_delay if request_delay is not None else settings.danbooru_request_delay
        self._client: Danbooru | None = None

        if not self.username or not self.api_key:
            raise ValueError(
                "Danbooru credentials are missing. "
                "Set input/danbooru.env or input/danbooru_api_key.txt (see input/danbooru.env.example)."
            )

    @property
    def client(self) -> Danbooru:
        if self._client is None:
            self._client = Danbooru(
                site_name="danbooru",
                username=self.username,
                api_key=self.api_key,
            )
        return self._client

    def _sleep(self) -> None:
        time.sleep(self.request_delay)

    def _handle_http_error(self, exc: PybooruHTTPError) -> None:
        status_code = exc.args[1] if len(exc.args) > 1 else None
        if status_code == 403:
            raise DanbooruAuthError(
                "Danbooru rejected the credentials (403 Forbidden). "
                "Check username and api_key in input/danbooru.env, then regenerate the API key at "
                "https://danbooru.donmai.us/profile if needed."
            ) from exc
        if status_code == 401:
            raise DanbooruAuthError(
                "Danbooru authentication failed (401 Unauthorized). "
                "Verify username and api_key in input/danbooru.env."
            ) from exc
        if status_code in {429, 500, 502, 503}:
            raise RuntimeError(
                f"Danbooru API temporary error ({status_code}). "
                "This often happens during bulk appearance extraction due to rate limits. "
                "Wait a few minutes, reduce concurrent jobs in Settings, or retry the series."
            ) from exc
        raise exc

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: PybooruHTTPError | None = None
        max_retries = max(1, settings.danbooru_request_retries)

        for attempt in range(max_retries):
            if attempt > 0:
                time.sleep(min(45.0, 2 ** attempt * 3))
            else:
                self._sleep()

            try:
                return self.client._get(path, params or {})
            except PybooruHTTPError as exc:
                status_code = exc.args[1] if len(exc.args) > 1 else None
                if status_code in {429, 500, 502, 503} and attempt < max_retries - 1:
                    last_exc = exc
                    continue
                self._handle_http_error(exc)

        if last_exc:
            self._handle_http_error(last_exc)
        raise RuntimeError("Danbooru request failed after retries")

    @staticmethod
    def _ensure_list(payload: Any, *, context: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and payload.get("success") is False:
            raise RuntimeError(f"Danbooru API error ({context}): {payload}")
        raise RuntimeError(f"Unexpected Danbooru response ({context}): {payload}")

    def verify_credentials(self) -> dict[str, Any]:
        payload = self._get_json(
            "tags.json",
            {
                "search[category]": 3,
                "search[hide_empty]": "yes",
                "search[order]": "count",
                "limit": 1,
                "page": 1,
            },
        )
        tags = self._ensure_list(payload, context="verify_credentials")
        return {
            "username": self.username,
            "verified_via": "pybooru",
            "pybooru_version": self._pybooru_version(),
            "sample_tag": tags[0]["name"] if tags else None,
        }

    @staticmethod
    def _pybooru_version() -> str:
        import pybooru

        return getattr(pybooru, "__version__", "unknown")

    def list_copyright_tags(
        self,
        *,
        page: int = 1,
        limit: int = 1000,
        hide_empty: str = "yes",
        order: str = "count",
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            "tags.json",
            {
                "search[category]": 3,
                "search[hide_empty]": hide_empty,
                "search[order]": order,
                "limit": limit,
                "page": page,
            },
        )
        return self._ensure_list(payload, context="list_copyright_tags")

    def list_character_tags_by_pattern(
        self,
        series_tag: str,
        *,
        page: int = 1,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            "tags.json",
            {
                "search[name_matches]": f"*_({series_tag})",
                "search[category]": self.CATEGORY_CHARACTER,
                "search[order]": "count",
                "limit": limit,
                "page": page,
            },
        )
        return self._ensure_list(payload, context="list_character_tags_by_pattern")

    def get_tags_by_names(self, tag_names: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for tag_name in tag_names:
            tag = self.get_tag(tag_name)
            if tag:
                results.append(tag)
        return results

    def get_tag(self, tag_name: str) -> dict[str, Any] | None:
        payload = self._get_json("tags.json", {"search[name]": tag_name})
        tags = self._ensure_list(payload, context="get_tag")
        return tags[0] if tags else None

    def list_posts(self, *, tags: str, page: int = 1, limit: int | None = None) -> list[dict[str, Any]]:
        payload = self._get_json(
            "posts.json",
            {
                "tags": tags,
                "page": page,
                "limit": limit or settings.danbooru_character_post_limit,
            },
        )
        return self._ensure_list(payload, context="list_posts")

    def count_posts(self, tags: str) -> int:
        payload = self._get_json("counts/posts.json", {"tags": tags})
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected Danbooru count response: {payload}")
        return int(payload.get("counts", {}).get("posts", 0))

    def get_related_tags(self, query: str, *, category: int | None = 0) -> dict[str, object]:
        last_exc: PybooruHTTPError | None = None
        max_retries = max(1, settings.danbooru_request_retries)

        for attempt in range(max_retries):
            if attempt > 0:
                time.sleep(min(45.0, 2 ** attempt * 3))
            else:
                self._sleep()

            try:
                payload = self.client.tag_related(query, category=category)
            except PybooruHTTPError as exc:
                status_code = exc.args[1] if len(exc.args) > 1 else None
                if status_code in {429, 500, 502, 503} and attempt < max_retries - 1:
                    last_exc = exc
                    continue
                self._handle_http_error(exc)
            else:
                if not isinstance(payload, dict):
                    raise RuntimeError(f"Unexpected Danbooru related_tag response: {payload}")
                return payload

        if last_exc:
            self._handle_http_error(last_exc)
        raise RuntimeError(f"Danbooru related_tag failed for '{query}' after retries")

    @staticmethod
    def build_search_tags(character_tag: str, series_tag: str) -> str:
        return f"{character_tag} {series_tag}"

    @staticmethod
    def build_danbooru_url(character_tag: str, series_tag: str) -> str:
        tags = DanbooruClient.build_search_tags(character_tag, series_tag)
        return f"{settings.danbooru_base_url}/posts?tags={quote(tags)}"
