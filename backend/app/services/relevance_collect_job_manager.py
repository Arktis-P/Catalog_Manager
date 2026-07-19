from __future__ import annotations

import threading
import uuid
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import job_write_context
from app.services.settings_service import SettingsService
from app.services.tag_relevance_service import TagRelevanceService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _PauseCancelledError(BaseException):
    """Raised when a paused job is cancelled before it resumes."""


@dataclass
class RelevanceCollectJobState:
    job_id: str
    character_ids: list[int]
    status: str = "queued"
    phase: str = "queued"
    message: str = "대기 중..."
    current: int = 0
    total: int = 0
    success_count: int = 0
    error_count: int = 0
    current_character_tag: str = ""
    errors: list[dict[str, object]] = field(default_factory=list)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class RelevanceCollectJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, RelevanceCollectJobState] = {}
        self._job_queue: deque[str] = deque()
        self._running_job_id: str | None = None
        self._cancel_requested: set[str] = set()
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()

    def _get_max_concurrent(self) -> int:
        db = SessionLocal()
        try:
            return SettingsService(db).get_collect_max_concurrent()
        finally:
            db.close()

    def start(self, character_ids: list[int]) -> RelevanceCollectJobState:
        job = RelevanceCollectJobState(
            job_id=str(uuid.uuid4()),
            character_ids=list(dict.fromkeys(character_ids)),
            total=len(set(character_ids)),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._job_queue.append(job.job_id)
        self._dispatch_next()
        return job

    def _dispatch_next(self) -> None:
        with self._lock:
            if self._running_job_id is not None:
                return
            while self._job_queue:
                job_id = self._job_queue.popleft()
                job = self._jobs.get(job_id)
                if not job or job.status != "queued":
                    continue
                self._running_job_id = job_id
                break
            else:
                return
        thread = threading.Thread(
            target=self._run,
            args=(job_id,),
            daemon=True,
            name=f"relevance-collect-{job_id[:8]}",
        )
        thread.start()

    def get_job(self, job_id: str) -> RelevanceCollectJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return False
        with self._pause_cond:
            self._paused_jobs.add(job_id)
        return True

    def resume(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"paused", "running"}:
                return False
            if job_id not in self._paused_jobs:
                return False
        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()
        return True

    def _check_pause(self, job_id: str) -> bool:
        if job_id not in self._paused_jobs:
            return True
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "paused"
                job.phase = "paused"
                job.message = "일시정지됨 · 재개 시 이어서 진행"
                job.current_character_tag = ""
        with self._pause_cond:
            while job_id in self._paused_jobs:
                self._pause_cond.wait(timeout=2.0)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status == "cancelled":
                raise _PauseCancelledError()
            job.status = "running"
            job.phase = "collecting"
            job.message = "작업 재개됨"
        return True

    def cancel(self, job_id: str) -> bool:
        was_queued = False
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"queued", "running", "paused"}:
                return False
            was_queued = job.status == "queued"
            self._cancel_requested.add(job_id)
            if was_queued:
                self._job_queue = deque(queued_id for queued_id in self._job_queue if queued_id != job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "취소됨" if was_queued else "취소 요청됨 · 현재 캐릭터 처리 후 중단"
            job.finished_at = _utc_now()
        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()
        if was_queued:
            self._dispatch_next()
        return True

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel_requested

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _run_one(self, job_id: str, character_id: int) -> tuple[int, str, str | None]:
        db = SessionLocal()
        character_tag = f"id:{character_id}"
        try:
            with job_write_context(job_id):
                character = db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
                if character is None:
                    raise ValueError("Character not found")
                character_tag = character.character_tag
                TagRelevanceService(db).collect_for_character(character)
            return character_id, character_tag, None
        except Exception as exc:
            db.rollback()
            return character_id, character_tag, str(exc)
        finally:
            db.close()

    def _record_result(
        self,
        job_id: str,
        *,
        character_id: int,
        character_tag: str,
        error: str | None,
        active_tags: dict[Future, str],
    ) -> None:
        current = self.get_job(job_id)
        if not current:
            return
        errors = list(current.errors)
        updates: dict[str, object] = {
            "status": "running",
            "phase": "collecting",
            "current": current.current + 1,
            "current_character_tag": character_tag,
        }
        if error is None:
            updates["success_count"] = current.success_count + 1
        else:
            errors.append({"character_id": character_id, "character_tag": character_tag, "error": error})
            updates["error_count"] = current.error_count + 1
            updates["errors"] = errors
        active_count = len(active_tags)
        total = current.total
        updates["message"] = f"{updates['current']}/{total} · 처리 중 {active_count}명"
        self._update(job_id, **updates)

    def _run(self, job_id: str) -> None:
        try:
            job = self.get_job(job_id)
            if not job or self._is_cancelled(job_id):
                return
            self._update(job_id, status="running", phase="collecting", message="관련도 수집 시작")

            pending_ids = deque(job.character_ids)
            active: dict[Future, str] = {}

            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="relevance-worker") as executor:
                while pending_ids or active:
                    if active:
                        done, _ = wait(active.keys(), timeout=0.05, return_when=FIRST_COMPLETED)
                        for future in done:
                            active.pop(future, None)
                            character_id, character_tag, error = future.result()
                            self._record_result(
                                job_id,
                                character_id=character_id,
                                character_tag=character_tag,
                                error=error,
                                active_tags=active,
                            )

                    if self._is_cancelled(job_id):
                        if active:
                            wait(active.keys())
                            for future in list(active):
                                active.pop(future, None)
                                character_id, character_tag, error = future.result()
                                self._record_result(
                                    job_id,
                                    character_id=character_id,
                                    character_tag=character_tag,
                                    error=error,
                                    active_tags=active,
                                )
                        return

                    if job_id in self._paused_jobs:
                        if active:
                            continue
                        self._check_pause(job_id)
                        continue

                    max_concurrent = max(1, self._get_max_concurrent())
                    while pending_ids and len(active) < max_concurrent and not self._is_cancelled(job_id):
                        self._check_pause(job_id)
                        if job_id in self._paused_jobs:
                            break
                        character_id = pending_ids.popleft()
                        submitted = executor.submit(self._run_one, job_id, character_id)
                        active[submitted] = f"id:{character_id}"
                        current = self.get_job(job_id)
                        if current:
                            self._update(
                                job_id,
                                message=f"{current.current}/{current.total} · 처리 중 {len(active)}명",
                            )

            current = self.get_job(job_id)
            if not current or self._is_cancelled(job_id):
                return
            self._update(
                job_id,
                status="completed",
                phase="completed",
                message=f"완료: 성공 {current.success_count} · 실패 {current.error_count}",
                current=current.total,
                current_character_tag="",
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            return
        finally:
            with self._lock:
                if self._running_job_id == job_id:
                    self._running_job_id = None
                self._cancel_requested.discard(job_id)
            with self._pause_cond:
                self._paused_jobs.discard(job_id)
            self._dispatch_next()


relevance_collect_job_manager = RelevanceCollectJobManager()
