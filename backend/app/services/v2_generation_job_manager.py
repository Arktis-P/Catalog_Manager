from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import job_write_context
from app.services.generation_service import GenerationService
from app.services.v2_generation_pipeline import V2GenerationPipeline, V2PipelineCancelled


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class V2GenerationJobState:
    job_id: str
    status: str = "queued"
    phase: str = "queued"
    message: str = "V2 자동 생성 대기 중..."
    current: int = 0
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_character_tag: str = ""
    errors: list[dict[str, object]] = field(default_factory=list)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class V2GenerationJobManager:
    """V2 자동 생성 배치를 하나씩 직렬 실행하고 진행률·취소를 관리한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, V2GenerationJobState] = {}
        self._queue: deque[str] = deque()
        self._arguments: dict[str, tuple[list[int] | None, bool]] = {}
        self._cancelled: set[str] = set()
        self._active_job_id: str | None = None
        self._lock = threading.Lock()

    def start(
        self,
        *,
        character_ids: list[int] | None = None,
        rerun: bool = False,
    ) -> V2GenerationJobState:
        job = V2GenerationJobState(job_id=str(uuid.uuid4()))
        with self._lock:
            self._jobs[job.job_id] = job
            self._queue.append(job.job_id)
            self._arguments[job.job_id] = (list(character_ids) if character_ids is not None else None, rerun)
        self._dispatch_next()
        return job

    def get_job(self, job_id: str) -> V2GenerationJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[V2GenerationJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda item: item.started_at, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return False
            self._cancelled.add(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "사용자가 취소했습니다."
            job.finished_at = _utc_now()
            return True

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _increment(self, job_id: str, **deltas: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in deltas.items():
                setattr(job, key, getattr(job, key) + value)

    def _append_error(self, job_id: str, payload: dict[str, object]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.errors.append(payload)

    def _dispatch_next(self) -> None:
        selected: tuple[str, list[int] | None, bool] | None = None
        with self._lock:
            if self._active_job_id is not None:
                return
            while self._queue:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                character_ids, rerun = self._arguments.pop(job_id, (None, False))
                self._active_job_id = job_id
                selected = (job_id, character_ids, rerun)
                break
        if selected is None:
            return
        thread = threading.Thread(
            target=self._run,
            args=selected,
            daemon=True,
            name=f"v2-generation-{selected[0][:8]}",
        )
        thread.start()

    @staticmethod
    def _target_characters(db, character_ids: list[int] | None, rerun: bool) -> list[GlobalCharacter]:
        query = db.query(GlobalCharacter)
        if character_ids is not None:
            if not character_ids:
                return []
            query = query.filter(GlobalCharacter.id.in_(character_ids))
            if not rerun:
                query = query.filter(GlobalCharacter.generation_status == "not_generated")
        else:
            query = query.filter(GlobalCharacter.generation_status == "not_generated")
        return query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.id.asc()).all()

    def _run(self, job_id: str, character_ids: list[int] | None, rerun: bool) -> None:
        db = SessionLocal()
        try:
            with job_write_context(job_id):
                service = GenerationService(db)
                status = service.naia_status()
                if not status.get("ready"):
                    self._update(
                        job_id,
                        status="failed",
                        phase="failed",
                        message=str(status.get("message") or "NAIA 연결 실패"),
                        finished_at=_utc_now(),
                    )
                    return

                characters = self._target_characters(db, character_ids, rerun)
                self._update(
                    job_id,
                    status="running",
                    phase="generating",
                    message=f"V2 자동 생성 시작 · {len(characters)}명",
                    total=len(characters),
                )
                pipeline = V2GenerationPipeline(db)
                for index, character in enumerate(characters, start=1):
                    if self._is_cancelled(job_id):
                        break
                    self._update(
                        job_id,
                        current=index - 1,
                        current_character_tag=character.character_tag,
                        message=f"{character.character_tag} 처리 중 ({index}/{len(characters)})",
                    )
                    try:
                        result = pipeline.run_character(
                            character.id,
                            should_cancel=lambda: self._is_cancelled(job_id),
                        )
                        self._increment(job_id, completed=1)
                        self._update(
                            job_id,
                            current=index,
                            message=f"{character.character_tag}: {result.generation_status}",
                        )
                    except V2PipelineCancelled:
                        break
                    except Exception as exc:
                        self._increment(job_id, failed=1)
                        self._append_error(
                            job_id,
                            {
                                "character_id": character.id,
                                "character_tag": character.character_tag,
                                "error": str(exc),
                            },
                        )
                        self._update(
                            job_id,
                            current=index,
                            message=f"{character.character_tag} 오류 후 계속: {exc}",
                        )

                snapshot = self.get_job(job_id)
                if self._is_cancelled(job_id):
                    final_status = "cancelled"
                elif snapshot and snapshot.completed == 0 and snapshot.failed:
                    final_status = "failed"
                else:
                    final_status = "completed"
                completed = snapshot.completed if snapshot else 0
                failed = snapshot.failed if snapshot else 0
                self._update(
                    job_id,
                    status=final_status,
                    phase=final_status,
                    message=f"완료 {completed}명 · 오류 {failed}명",
                    finished_at=_utc_now(),
                )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                phase="failed",
                message="V2 자동 생성 작업 오류",
                errors=[{"error": str(exc)}],
                finished_at=_utc_now(),
            )
        finally:
            db.close()
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None
            self._dispatch_next()


v2_generation_job_manager = V2GenerationJobManager()
