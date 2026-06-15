from __future__ import annotations

import time
import uuid
from typing import Any

import requests


class NaiaClientError(Exception):
    pass


class NaiaConnectionError(NaiaClientError):
    pass


class NaiaGenerationError(NaiaClientError):
    pass


class NaiaClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = self._session.request(
                method,
                self._url(path),
                timeout=kwargs.pop("timeout", self.timeout),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise NaiaConnectionError(f"NAIA 연결 실패 ({self.base_url}): {exc}") from exc
        return response

    def check_health(self) -> dict[str, Any]:
        response = self._request("GET", "/api/status")
        if response.status_code != 200:
            raise NaiaConnectionError(f"NAIA 상태 확인 실패: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise NaiaConnectionError("NAIA 상태 응답 형식이 올바르지 않습니다.")
        return payload

    def get_queue_state(self) -> dict[str, Any]:
        response = self._request("GET", "/api/queue/state")
        if response.status_code != 200:
            raise NaiaClientError(f"NAIA 큐 상태 조회 실패: HTTP {response.status_code}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def list_history(self, *, page: int = 0, per_page: int = 5) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/api/history/list?page={page}&per_page={per_page}",
        )
        if response.status_code != 200:
            raise NaiaClientError(f"NAIA 히스토리 조회 실패: HTTP {response.status_code}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        overrides: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "generate",
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "request_id": request_id or str(uuid.uuid4()),
            "overrides": {
                "prompt_fixed": True,
                **(overrides or {}),
            },
        }
        response = self._request(
            "POST",
            "/api/generate",
            json=payload,
            timeout=max(self.timeout, 60.0),
        )
        data = response.json() if response.content else {}
        if response.status_code != 200:
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "")
            raise NaiaGenerationError(message or f"NAIA 생성 요청 실패: HTTP {response.status_code}")
        return data if isinstance(data, dict) else {}

    def download_history_image(self, history_id: str) -> bytes:
        response = self._request(
            "GET",
            f"/api/history/image/{history_id}",
            timeout=max(self.timeout, 120.0),
        )
        if response.status_code != 200:
            raise NaiaClientError(f"NAIA 이미지 다운로드 실패: HTTP {response.status_code}")
        return response.content

    def wait_for_idle(
        self,
        *,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.get_queue_state()
            if not state.get("is_generating") and int(state.get("total") or 0) == 0:
                return
            time.sleep(poll_interval)
        raise NaiaGenerationError("NAIA 생성 대기 시간이 초과되었습니다.")

    def wait_for_new_history(
        self,
        known_ids: set[str],
        *,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self.list_history(page=0, per_page=10)
            images = history.get("images")
            if isinstance(images, list):
                for item in images:
                    if not isinstance(item, dict):
                        continue
                    history_id = str(item.get("history_id") or "")
                    if history_id and history_id not in known_ids:
                        return item
            state = self.get_queue_state()
            if not state.get("is_generating") and int(state.get("total") or 0) == 0:
                history = self.list_history(page=0, per_page=10)
                images = history.get("images")
                if isinstance(images, list):
                    for item in images:
                        if not isinstance(item, dict):
                            continue
                        history_id = str(item.get("history_id") or "")
                        if history_id and history_id not in known_ids:
                            return item
                break
            time.sleep(poll_interval)
        raise NaiaGenerationError("NAIA에서 새 이미지를 받지 못했습니다.")
