from __future__ import annotations

import random
import time
from collections.abc import Callable

from app.integrations.naia.client import NaiaClient, NaiaClientError

GENERATION_GAP_SECONDS_MIN = 0.5
GENERATION_GAP_SECONDS_MAX = 2.0
GENERATION_MAX_ATTEMPTS = 2


def wait_between_naia_generations() -> float:
    """연속 NAIA 생성 요청 사이 랜덤 대기 (0.5~2초)."""
    delay = random.uniform(GENERATION_GAP_SECONDS_MIN, GENERATION_GAP_SECONDS_MAX)
    time.sleep(delay)
    return delay


def generate_and_fetch_image(
    client: NaiaClient,
    *,
    prompt: str,
    negative_prompt: str,
    known_history_ids: set[str],
    max_attempts: int = GENERATION_MAX_ATTEMPTS,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> tuple[bytes, str]:
    """NAIA로 이미지 생성 후 다운로드. 실패 시 동일 프롬프트로 재시도."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client.generate(prompt=prompt, negative_prompt=negative_prompt)
            history_item = client.wait_for_new_history(known_history_ids, timeout=300.0)
            history_id = str(history_item.get("history_id") or "")
            if not history_id:
                raise NaiaClientError("history_id가 비어 있습니다.")
            image_bytes = client.download_history_image(history_id)
            known_history_ids.add(history_id)
            return image_bytes, history_id
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            if on_retry:
                on_retry(attempt, exc)
            wait_between_naia_generations()

    message = str(last_error) if last_error else "NAIA 이미지 생성 실패"
    raise NaiaClientError(f"{message} (재시도 {max_attempts}회 후 실패)") from last_error
