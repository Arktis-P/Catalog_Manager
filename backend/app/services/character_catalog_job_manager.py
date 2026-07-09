from __future__ import annotations

import threading
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.danbooru.client import DanbooruAuthError
from app.models.global_character import GlobalCharacter
from app.services.character_catalog_service import CharacterCatalogService
from app.services.db_write_queue import job_write_context
from app.services.settings_service import SettingsService

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
    active_items: list[str] = field(default_factory=list)
    error: str | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class CharacterCatalogJobManager:
    """Job queue for character-catalog jobs (list collection + tag collection).

    Kept fully independent from SeriesJobManager so it cannot affect the
    existing Series feature; the only shared resources are the DB write
    queue (serializes commits) and the settings-driven concurrency limit
    (same "Danbooru 동시 요청 개수" setting used by SeriesJobManager).

    Each "job" (individual click, bulk selection, or retry-failed) is a
    single progress entry, but the actual per-character Danbooru work for
    ALL tags jobs is submitted to one shared, settings-sized thread pool
    (`_get_tags_executor`) so e.g. a 200-character bulk selection is
    processed N at a time (N = concurrency setting) instead of one at a
    time, while still reporting a single aggregated progress card.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, CatalogJobState] = {}
        self._job_queue: deque[str] = deque()
        self._job_kwargs: dict[str, dict] = {}
        self._running_job_ids: set[str] = set()
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()
        self._executor_lock = threading.Lock()
        self._tags_executor: ThreadPoolExecutor | None = None
        self._tags_executor_size = 0

    def _get_max_concurrent(self) -> int:
        db = SessionLocal()
        try:
            return SettingsService(db).get_collect_max_concurrent()
        finally:
            db.close()

    def _get_tags_executor(self) -> ThreadPoolExecutor:
        """Shared pool sized to the concurrency setting; every character-tag
        task from every tags job (individual/bulk/retry) goes through this
        single pool, so total concurrent Danbooru work stays bounded across
        jobs, not just within one job."""
        max_workers = max(1, self._get_max_concurrent())
        with self._executor_lock:
            if self._tags_executor is None or self._tags_executor_size != max_workers:
                old = self._tags_executor
                self._tags_executor = ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="catalog-tags"
                )
                self._tags_executor_size = max_workers
                if old is not None:
                    old.shutdown(wait=False)
            return self._tags_executor

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

    def start_catalog_list(
        self, *, min_post_count: int, restart: bool = False, only_new: bool = False
    ) -> CatalogJobState:
        return self._enqueue(
            JOB_TYPE_CATALOG_LIST, min_post_count=min_post_count, restart=restart, only_new=only_new
        )

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
        # Job "containers" start immediately (they mostly just submit work to
        # the shared tags executor and wait) - the real concurrency bound is
        # enforced inside that shared executor, not here.
        to_start: list[tuple[str, str, dict]] = []
        with self._lock:
            while self._job_queue:
                job_id = self._job_queue.popleft()
                job = self._jobs.get(job_id)
                if not job or job.status != "queued":
                    continue
                self._running_job_ids.add(job_id)
                kwargs = self._job_kwargs.pop(job_id, {})
                to_start.append((job_id, job.job_type, kwargs))

        for job_id, job_type, kwargs in to_start:
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
            self._finish_job(job_id)

    def _finish_job(self, job_id: str) -> None:
        with self._lock:
            self._running_job_ids.discard(job_id)
        self._dispatch_next()

    def _run_catalog_list(
        self, job_id: str, db, *, min_post_count: int, restart: bool = False, only_new: bool = False
    ) -> None:
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

            result = service.collect_list(
                min_post_count=min_post_count, only_new=only_new, progress_callback=on_progress
            )

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
            total = len(character_ids)
            max_workers = max(1, self._get_max_concurrent())
            self._update_job(
                job_id,
                status="running",
                phase="starting",
                message=f"통합 태그 수집 시작 · 대상 {total}명 · 동시 {max_workers}개",
                total=total,
            )

            state_lock = threading.Lock()
            counters = {"success": 0, "partial": 0, "failed": 0, "done": 0}
            active_tags: dict[int, str] = {}

            def process_one(character_id: int) -> None:
                worker_db = SessionLocal()
                try:
                    with job_write_context(job_id):
                        character = (
                            worker_db.query(GlobalCharacter)
                            .filter(GlobalCharacter.id == character_id)
                            .first()
                        )
                        if not character:
                            with state_lock:
                                counters["failed"] += 1
                                counters["done"] += 1
                            return

                        character.collect_status = "collecting"
                        with state_lock:
                            active_tags[character_id] = character.character_tag
                            self._update_job(job_id, active_items=list(active_tags.values()))

                        service = CharacterCatalogService(worker_db)
                        result = service.collect_tags_for_character(character)

                        with state_lock:
                            active_tags.pop(character_id, None)
                            if result.success:
                                counters["success"] += 1
                            elif result.appearance_ok or result.series_ok:
                                counters["partial"] += 1
                            else:
                                counters["failed"] += 1
                            counters["done"] += 1
                            self._update_job(
                                job_id,
                                status="running",
                                phase="collecting",
                                message=(
                                    f"{counters['done']}/{total} · {character.character_tag} 처리 완료"
                                    f" (동시 {max_workers}개 진행)"
                                ),
                                current=counters["done"],
                                current_character_tag=character.character_tag,
                                active_items=list(active_tags.values()),
                                success_count=counters["success"],
                                partial_count=counters["partial"],
                                failed_count=counters["failed"],
                            )
                finally:
                    worker_db.close()

            # 새 작업을 공유 실행기에 제출하기 전마다 일시정지/취소 체크포인트를 거친다.
            # (이미 제출되어 실행 중인 작업은 취소/일시정지와 무관하게 끝까지 완료된다.)
            futures: list[Future] = []
            executor = self._get_tags_executor()
            for character_id in character_ids:
                self._check_pause(job_id)
                futures.append(executor.submit(process_one, character_id))

            for future in futures:
                future.result()

            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                message=f"완료: 성공 {counters['success']} · 부분 완료 {counters['partial']} · 실패 {counters['failed']}",
                current=total,
                success_count=counters["success"],
                partial_count=counters["partial"],
                failed_count=counters["failed"],
                active_items=[],
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            self._update_job(job_id, active_items=[])
            return
        except DanbooruAuthError as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="Danbooru 인증 실패", error=str(exc),
                active_items=[], finished_at=_utc_now(),
            )
        except Exception as exc:
            self._update_job(
                job_id, status="failed", phase="failed", message="통합 태그 수집 중 오류 발생", error=str(exc),
                active_items=[], finished_at=_utc_now(),
            )


character_catalog_job_manager = CharacterCatalogJobManager()
