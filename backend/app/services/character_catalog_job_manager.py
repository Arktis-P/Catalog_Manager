from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.danbooru.client import DanbooruAuthError
from app.models.global_character import GlobalCharacter
from app.services.character_catalog_service import CharacterCatalogService
from app.services.db_write_queue import job_write_context

JOB_TYPE_CATALOG_LIST = "character_catalog_list"
JOB_TYPE_CATALOG_TAGS = "character_catalog_tags"

DEFAULT_MIN_POST_COUNT = 10


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _PauseCancelledError(BaseException):
    """Raised from progress callback when a job is cancelled while paused."""


@dataclass
class CatalogJobState:
    job_id: str
    job_type: str
    status: str = "queued"
    phase: str = "queued"
    message: str = "대기 중..."
    current: int = 0
    total: int = 0
    created: int = 0
    updated: int = 0
    success_count: int = 0
    partial_count: int = 0
    failed_count: int = 0
    current_character_tag: str = ""
    error: str | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class CharacterCatalogJobManager:
    """Sequential job queue for character-catalog jobs (list collection + tag collection).

    Kept fully independent from SeriesJobManager so it cannot affect the
    existing Series feature; the only shared resources are the DB write
    queue (serializes commits) and the Danbooru client's own rate limiting.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, CatalogJobState] = {}
        self._job_queue: deque[str] = deque()
        self._job_kwargs: dict[str, dict] = {}
        self._running_job_id: str | None = None
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()

    def get_job(self, job_id: str) -> CatalogJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[CatalogJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        running = [j for j in jobs if j.status in {"running", "paused"}]
        queued = [j for j in jobs if j.status == "queued"]
        done = sorted(
            [j for j in jobs if j.status in {"completed", "failed", "cancelled"}],
            key=lambda j: j.started_at,
            reverse=True,
        )
        return (running + queued + done)[:limit]

    def start_catalog_list(self, *, min_post_count: int, restart: bool = False) -> CatalogJobState:
        return self._enqueue(JOB_TYPE_CATALOG_LIST, min_post_count=min_post_count, restart=restart)

    def start_catalog_tags(self, character_ids: list[int]) -> CatalogJobState:
        return self._enqueue(JOB_TYPE_CATALOG_TAGS, character_ids=character_ids)

    def pause_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return False
        with self._pause_cond:
            self._paused_jobs.add(job_id)
        return True

    def resume_job(self, job_id: str) -> bool:
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
        with self._pause_cond:
            while job_id in self._paused_jobs:
                self._pause_cond.wait(timeout=2.0)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status == "cancelled":
                raise _PauseCancelledError()
            job.status = "running"
            job.message = "작업 재개됨"
        return True

    def cancel_job(self, job_id: str) -> bool:
        was_paused = False
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"queued", "paused"}:
                return False
            was_paused = job.status == "paused"
            if not was_paused:
                self._job_queue = deque(jid for jid in self._job_queue if jid != job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "취소됨"
            job.finished_at = _utc_now()

        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()

        if not was_paused:
            self._dispatch_next()
        return True

    def _enqueue(self, job_type: str, **kwargs: object) -> CatalogJobState:
        with self._lock:
            job = CatalogJobState(job_id=str(uuid.uuid4()), job_type=job_type)
            self._jobs[job.job_id] = job
            self._job_queue.append(job.job_id)
            self._job_kwargs[job.job_id] = kwargs
        self._dispatch_next()
        return job

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _dispatch_next(self) -> None:
        with self._lock:
            if self._running_job_id is not None or not self._job_queue:
                return
            job_id = self._job_queue.popleft()
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return
            self._running_job_id = job_id
            kwargs = self._job_kwargs.pop(job_id, {})
            job_type = job.job_type

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, job_type, kwargs),
            daemon=True,
            name=f"{job_type}-{job_id[:8]}",
        )
        thread.start()

    def _run_job(self, job_id: str, job_type: str, kwargs: dict) -> None:
        db = SessionLocal()
        try:
            with job_write_context(job_id):
                if job_type == JOB_TYPE_CATALOG_LIST:
                    self._run_catalog_list(job_id, db, **kwargs)
                else:
                    self._run_catalog_tags(job_id, db, **kwargs)
        finally:
            db.close()
            with self._lock:
                if self._running_job_id == job_id:
                    self._running_job_id = None
            self._dispatch_next()

    def _run_catalog_list(self, job_id: str, db, *, min_post_count: int, restart: bool = False) -> None:
        try:
            service = CharacterCatalogService(db)
            if restart:
                service.reset_checkpoint()

            self._update_job(job_id, status="running", phase="starting", message="캐릭터 목록 수집 시작")

            def on_progress(payload: dict[str, object]) -> None:
                self._update_job(
                    job_id,
                    status="running",
                    phase=payload.get("phase", "listing"),
                    message=payload.get("message", ""),
                    current=payload.get("current", 0),
                    created=payload.get("created", 0),
                    updated=payload.get("updated", 0),
                )
                self._check_pause(job_id)

            result = service.collect_list(min_post_count=min_post_count, progress_callback=on_progress)

            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                message=f"완료: {result.pages_processed}페이지 · 신규 {result.created} · 갱신 {result.updated}",
                created=result.created,
                updated=result.updated,
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            return
        except DanbooruAuthError as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="Danbooru 인증 실패", error=str(exc), finished_at=_utc_now()
            )
        except Exception as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="목록 수집 중 오류 발생", error=str(exc), finished_at=_utc_now()
            )

    def _run_catalog_tags(self, job_id: str, db, *, character_ids: list[int]) -> None:
        try:
            service = CharacterCatalogService(db)
            total = len(character_ids)
            self._update_job(
                job_id,
                status="running",
                phase="starting",
                message=f"통합 태그 수집 시작 · 대상 {total}명",
                total=total,
            )

            success = 0
            partial = 0
            failed = 0

            for index, character_id in enumerate(character_ids, start=1):
                character = db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
                if not character:
                    failed += 1
                    continue

                character.collect_status = "collecting"
                self._update_job(
                    job_id,
                    status="running",
                    phase="collecting",
                    message=f"{index}/{total} · {character.character_tag} 통합 태그 수집 중",
                    current=index,
                    current_character_tag=character.character_tag,
                    success_count=success,
                    partial_count=partial,
                    failed_count=failed,
                )
                self._check_pause(job_id)

                result = service.collect_tags_for_character(character)
                if result.success:
                    success += 1
                elif result.appearance_ok or result.series_ok:
                    partial += 1
                else:
                    failed += 1

            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                message=f"완료: 성공 {success} · 부분 완료 {partial} · 실패 {failed}",
                current=total,
                success_count=success,
                partial_count=partial,
                failed_count=failed,
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            return
        except DanbooruAuthError as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="Danbooru 인증 실패", error=str(exc), finished_at=_utc_now()
            )
        except Exception as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="통합 태그 수집 중 오류 발생", error=str(exc), finished_at=_utc_now()
            )


character_catalog_job_manager = CharacterCatalogJobManager()
