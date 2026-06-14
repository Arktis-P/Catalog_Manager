from __future__ import annotations

import time
from typing import Any

import requests
from pybooru import Danbooru
from requests.auth import HTTPBasicAuth

from app.config import settings


class DanbooruAuthError(Exception):
    pass


class DanbooruClient:
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
        self._auth = HTTPBasicAuth(self.username, self.api_key)

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

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        return requests.get(
            f"{settings.danbooru_base_url}{path}",
            auth=self._auth,
            params=params,
            timeout=30,
            headers={"User-Agent": "CatalogueManager/0.2 (+local app)"},
        )

    def verify_credentials(self) -> dict[str, Any]:
        response = self._request(
            "/tags.json",
            params={
                "search[category]": 3,
                "search[hide_empty]": "yes",
                "search[order]": "count",
                "limit": 1,
                "page": 1,
            },
        )

        if response.status_code == 403:
            raise DanbooruAuthError(
                "Danbooru rejected the credentials (403 Forbidden). "
                "Check username and api_key in input/danbooru.env, then regenerate the API key at "
                "https://danbooru.donmai.us/profile if needed."
            )
        if response.status_code == 401:
            raise DanbooruAuthError(
                "Danbooru authentication failed (401 Unauthorized). "
                "Verify username and api_key in input/danbooru.env."
            )

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise DanbooruAuthError(f"Unexpected Danbooru response during verification: {payload}")

        return {
            "username": self.username,
            "verified_via": "tags.json",
            "sample_tag": payload[0]["name"] if payload else None,
        }

    def list_copyright_tags(
        self,
        *,
        page: int = 1,
        limit: int = 1000,
        hide_empty: str = "yes",
        order: str = "count",
    ) -> list[dict[str, Any]]:
        time.sleep(self.request_delay)
        response = self._request(
            "/tags.json",
            params={
                "search[category]": 3,
                "search[hide_empty]": hide_empty,
                "search[order]": order,
                "limit": limit,
                "page": page,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Danbooru API error: {payload}")
        return payload
