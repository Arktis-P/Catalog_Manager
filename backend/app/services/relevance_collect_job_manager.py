from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import job_write_context
from app.services.tag_relevance_service import TagRelevanceService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"queued", "running"}:
                return False
            was_queued = job.status == "queued"
            self._cancel_requested.add(job_id)
            if was_queued:
                self._job_queue = deque(queued_id for queued_id in self._job_queue if queued_id != job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "취소됨" if was_queued else "취소 요청됨 · 현재 캐릭터 처리 후 중단"
            job.finished_at = _utc_now()
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

    def _run(self, job_id: str) -> None:
        try:
            job = self.get_job(job_id)
            if not job or self._is_cancelled(job_id):
                return
            self._update(job_id, status="running", phase="collecting", message="관련도 수집 시작")

            for index, character_id in enumerate(job.character_ids, start=1):
                if self._is_cancelled(job_id):
                    return
                db = SessionLocal()
                character_tag = f"id:{character_id}"
                try:
                    with job_write_context(job_id):
                        character = (
                            db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
                        )
                        if character is None:
                            raise ValueError("Character not found")
                        character_tag = character.character_tag
                        self._update(
                            job_id,
                            current_character_tag=character_tag,
                            message=f"{index}/{job.total} · {character_tag} 수집 중",
                        )
                        TagRelevanceService(db).collect_for_character(character)
                    current = self.get_job(job_id)
                    self._update(
                        job_id,
                        current=index,
                        success_count=(current.success_count if current else 0) + 1,
                    )
                except Exception as exc:
                    db.rollback()
                    current = self.get_job(job_id)
                    errors = list(current.errors if current else [])
                    errors.append(
                        {"character_id": character_id, "character_tag": character_tag, "error": str(exc)}
                    )
                    self._update(
                        job_id,
                        current=index,
                        error_count=(current.error_count if current else 0) + 1,
                        errors=errors,
                    )
                finally:
                    db.close()

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
        finally:
            with self._lock:
                if self._running_job_id == job_id:
                    self._running_job_id = None
                self._cancel_requested.discard(job_id)
            self._dispatch_next()


relevance_collect_job_manager = RelevanceCollectJobManager()
