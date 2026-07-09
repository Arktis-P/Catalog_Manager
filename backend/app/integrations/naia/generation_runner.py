from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable

from app.integrations.naia.client import NaiaClient, NaiaClientError

GENERATION_GAP_SECONDS_MIN = 0.5
GENERATION_GAP_SECONDS_MAX = 2.0
GENERATION_MAX_ATTEMPTS = 2

# NAIA는 로컬에서 단일 요청만 처리할 수 있는 리소스이므로, 서로 다른 생성 큐
# (메인 시리즈/캐릭터 생성 큐, 리뷰 재생성 큐)가 동시에 요청을 보내면 history_id가
# 뒤섞여 다른 큐의 이미지를 가로채는 문제가 생긴다. 프로세스 전역 락으로 실제
# generate+wait+download 시퀀스를 항상 하나씩만 실행되게 강제한다.
_naia_call_lock = threading.Lock()

# 각 생성 큐(메인 시리즈/캐릭터 목록/리뷰 재생성)는 저마다 자신만의 known_history_ids
# 집합을 들고 있었는데, 이게 서로 공유되지 않아 "다른 큐가 방금 클레임한 이미지"를
# 모르는 채로 wait_for_new_history를 호출하는 경우가 있었다. 그 결과 방금 다른 큐가
# 생성한, 전혀 관련 없는 캐릭터의 이미지를 "새 이미지"로 오인해 가로채는 문제가
# 발생했다 (history_id 뒤섞임). 모든 큐가 이 프로세스 전역 레지스트리를 함께
# 체크·갱신하게 해서, 어느 큐가 요청했든 이미 응답으로 소비된 history_id는 다시
# 다른 호출에 "새 이미지"로 잡히지 않도록 한다. _naia_call_lock 보유 중에만
# 읽고 쓰므로 별도 락이 필요 없다.
_claimed_history_ids: set[str] = set()
_claimed_history_order: deque[str] = deque()
_CLAIMED_HISTORY_CAP = 500


def _claim_history_id(history_id: str) -> None:
    if history_id in _claimed_history_ids:
        return
    _claimed_history_ids.add(history_id)
    _claimed_history_order.append(history_id)
    while len(_claimed_history_order) > _CLAIMED_HISTORY_CAP:
        oldest = _claimed_history_order.popleft()
        _claimed_history_ids.discard(oldest)


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
            with _naia_call_lock:
                # 이 호출자가 모르는 항목이라도 다른 큐가 이미 클레임했다면 제외해야,
                # 서로 다른 큐가 상대방이 방금 받아간 이미지를 "새 이미지"로 착각해
                # 가로채는 일이 없다.
                excluded_ids = known_history_ids | _claimed_history_ids
                client.generate(prompt=prompt, negative_prompt=negative_prompt)
                history_item = client.wait_for_new_history(excluded_ids, timeout=300.0)
                history_id = str(history_item.get("history_id") or "")
                if not history_id:
                    raise NaiaClientError("history_id가 비어 있습니다.")
                image_bytes = client.download_history_image(history_id)
                known_history_ids.add(history_id)
                _claim_history_id(history_id)
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
