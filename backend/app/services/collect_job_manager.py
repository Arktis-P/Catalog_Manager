from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.danbooru.client import DanbooruAuthError
from app.models.character import Character
from app.models.series import Series
from app.services.appearance_service import AppearanceService
from app.services.character_service import CharacterService
from app.services.db_write_queue import job_write_context
from app.services.settings_service import SettingsService

JOB_TYPE_CHARACTER_COLLECT = "character_collect"
JOB_TYPE_APPEARANCE_EXTRACT = "appearance_extract"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _PauseCancelledError(BaseException):
    """Raised from progress callback when a job is cancelled while paused.
    Inherits BaseException so 'except Exception' blocks in service code don't catch it."""


@dataclass
class SeriesJobState:
    job_id: str
    series_id: int
    series_tag: str
    job_type: str = JOB_TYPE_CHARACTER_COLLECT
    status: str = "queued"
    phase: str = "queued"
    message: str = "대기 중..."
    current: int = 0
    total: int = 0
    discovered: int = 0
    created: int = 0
    skipped_existing: int = 0
    updated: int = 0
    error: str | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


CollectJobState = SeriesJobState


class SeriesJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, SeriesJobState] = {}
        self._active_by_series: dict[int, str] = {}
        self._job_queue: deque[str] = deque()
        self._running_job_ids: set[str] = set()
        self._running_count = 0
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()

    def _get_max_concurrent(self) -> int:
        db = SessionLocal()
        try:
            return SettingsService(db).get_collect_max_concurrent()
        finally:
            db.close()

    def set_max_concurrent(self, _value: int) -> None:
        self._dispatch_next()

    def get_job(self, job_id: str) -> SeriesJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_running_jobs(self) -> list[SeriesJobState]:
        with self._lock:
            return [self._jobs[jid] for jid in self._running_job_ids if jid in self._jobs]

    def get_active_job_for_series(self, series_id: int) -> SeriesJobState | None:
        with self._lock:
            job_id = self._active_by_series.get(series_id)
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[SeriesJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
            queue_order: dict[str, int] = {
                job_id: idx for idx, job_id in enumerate(self._job_queue)
            }

        running = [j for j in jobs if j.status in {"running", "paused"}]
        queued = sorted(
            [j for j in jobs if j.status == "queued"],
            key=lambda j: queue_order.get(j.job_id, 999_999),
        )
        done = sorted(
            [j for j in jobs if j.status in {"completed", "failed", "cancelled"}],
            key=lambda j: j.started_at,
            reverse=True,
        )

        # running 전체 + 큐 앞쪽 N개 + 최근 완료 N개
        n_running = len(running)
        n_queued_slots = max(0, limit - n_running - 5)
        result = running + queued[:n_queued_slots] + done[:5]
        return result[:limit]

    def start_series_collect(self, series_id: int, series_tag: str = "") -> SeriesJobState:
        return self._enqueue(series_id, JOB_TYPE_CHARACTER_COLLECT, series_tag=series_tag)

    def start_appearance_extract(self, series_id: int, series_tag: str = "") -> SeriesJobState:
        return self._enqueue(series_id, JOB_TYPE_APPEARANCE_EXTRACT, series_tag=series_tag)

    def pause_job(self, job_id: str) -> bool:
        """현재 실행 중인 작업을 일시정지 요청. 다음 체크포인트에서 멈춤."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return False
        with self._pause_cond:
            self._paused_jobs.add(job_id)
        return True

    def resume_job(self, job_id: str) -> bool:
        """일시정지된 작업 재개."""
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
        """체크포인트. 일시정지 요청이 있으면 재개될 때까지 대기.
        Returns True to continue, raises _PauseCancelledError if cancelled during pause."""
        if job_id not in self._paused_jobs:
            return True

        # 일시정지 상태로 전환
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "paused"
                job.phase = "paused"
                job.message = "일시정지됨 · 재개 시 이어서 진행"

        # 재개 또는 취소될 때까지 대기
        with self._pause_cond:
            while job_id in self._paused_jobs:
                self._pause_cond.wait(timeout=2.0)

        # 취소 여부 확인
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
                self._job_queue = deque(queued_id for queued_id in self._job_queue if queued_id != job_id)

            task_label = "수집" if job.job_type == JOB_TYPE_CHARACTER_COLLECT else "외형 추출"
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = f"{task_label} 취소됨"
            job.finished_at = _utc_now()

            if self._active_by_series.get(job.series_id) == job_id:
                self._active_by_series.pop(job.series_id, None)

            self._refresh_queue_messages()

        # 일시정지 중인 스레드 깨우기 (취소 처리)
        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()

        if not was_paused:
            self._dispatch_next()
        # was_paused인 경우: 스레드가 깨어나서 _PauseCancelledError → _finish_job → _dispatch_next 호출

        return True

    def _enqueue(self, series_id: int, job_type: str, series_tag: str = "") -> SeriesJobState:
        with self._lock:
            existing_job_id = self._active_by_series.get(series_id)
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running", "paused"}:
                    return existing

            job = SeriesJobState(
                job_id=str(uuid.uuid4()),
                series_id=series_id,
                series_tag=series_tag,
                job_type=job_type,
            )
            self._jobs[job.job_id] = job
            self._active_by_series[series_id] = job.job_id
            self._job_queue.append(job.job_id)
            self._refresh_queue_messages()

        self._dispatch_next()
        return job

    def _refresh_queue_messages(self) -> None:
        max_concurrent = self._get_max_concurrent()
        slots_available = max_concurrent - self._running_count
        for index, queued_job_id in enumerate(self._job_queue, start=1):
            queued_job = self._jobs.get(queued_job_id)
            if not queued_job or queued_job.status != "queued":
                continue
            task_label = "수집" if queued_job.job_type == JOB_TYPE_CHARACTER_COLLECT else "외형 추출"
            if index <= slots_available:
                queued_job.message = f"{task_label} 대기 중 · 곧 시작"
            else:
                jobs_ahead = self._running_count + (index - slots_available - 1)
                queued_job.message = f"{task_label} 대기 중 · 앞에 {jobs_ahead}개"

    def _dispatch_next(self) -> None:
        max_concurrent = self._get_max_concurrent()
        with self._lock:
            while self._running_count < max_concurrent and self._job_queue:
                job_id = self._job_queue.popleft()
                job = self._jobs.get(job_id)
                if not job or job.status != "queued":
                    continue

                self._running_count += 1
                self._running_job_ids.add(job_id)
                series_id = job.series_id
                job_type = job.job_type
                thread = threading.Thread(
                    target=self._run_job,
                    args=(job_id, series_id, job_type),
                    daemon=True,
                    name=f"{job_type}-{series_id}",
                )
                thread.start()

            self._refresh_queue_messages()

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _run_job(self, job_id: str, series_id: int, job_type: str) -> None:
        if job_type == JOB_TYPE_APPEARANCE_EXTRACT:
            self._run_appearance_extract(job_id, series_id)
        else:
            self._run_series_collect(job_id, series_id)

    def _run_series_collect(self, job_id: str, series_id: int) -> None:
        db = SessionLocal()
        try:
            with job_write_context(job_id):
                self._run_series_collect_inner(job_id, series_id, db)
        finally:
            db.close()
            self._finish_job(job_id, series_id)

    def _run_series_collect_inner(self, job_id: str, series_id: int, db) -> None:
        try:
            series = db.query(Series).filter(Series.id == series_id).first()
            if not series:
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message="Series not found",
                    error="Series not found",
                    finished_at=_utc_now(),
                )
                return

            self._update_job(
                job_id,
                status="running",
                phase="starting",
                message=f"{series.series_tag} 캐릭터 수집 시작",
                series_tag=series.series_tag,
            )

            def on_progress(payload: dict[str, object]) -> None:
                updates: dict[str, object] = {
                    "status": "running",
                    "phase": payload.get("phase", "running"),
                    "message": payload.get("message", ""),
                    "current": payload.get("current", 0),
                    "total": payload.get("total", 0),
                }
                if "discovered" in payload:
                    updates["discovered"] = payload["discovered"]
                self._update_job(job_id, **updates)
                # 체크포인트: 일시정지 요청 시 여기서 블록
                self._check_pause(job_id)

            service = CharacterService(db)
            result = service.collect_for_series(series, progress_callback=on_progress)

            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                message=(
                    f"완료: discovered {result.discovered}, "
                    f"added {result.created}, skipped {result.skipped_existing}"
                ),
                discovered=result.discovered,
                created=result.created,
                skipped_existing=result.skipped_existing,
                current=result.discovered,
                total=result.discovered,
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            # 일시정지 중 취소됨 - status는 cancel_job에서 이미 설정됨
            return
        except DanbooruAuthError as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="Danbooru 인증 실패",
                error=str(exc),
                finished_at=_utc_now(),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="수집 중 오류 발생",
                error=str(exc),
                finished_at=_utc_now(),
            )

    def _run_appearance_extract(self, job_id: str, series_id: int) -> None:
        db = SessionLocal()
        try:
            with job_write_context(job_id):
                self._run_appearance_extract_inner(job_id, series_id, db)
        finally:
            db.close()
            self._finish_job(job_id, series_id)

    def _run_appearance_extract_inner(self, job_id: str, series_id: int, db) -> None:
        try:
            series = db.query(Series).filter(Series.id == series_id).first()
            if not series:
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message="Series not found",
                    error="Series not found",
                    finished_at=_utc_now(),
                )
                return

            character_count = db.query(Character).filter(Character.series_id == series_id).count()
            if character_count <= 0:
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message="캐릭터 수집이 먼저 필요합니다",
                    error="No characters to extract appearance tags for",
                    finished_at=_utc_now(),
                )
                return

            self._update_job(
                job_id,
                status="running",
                phase="starting",
                message=f"{series.series_tag} 외형 태그 추출 시작",
                series_tag=series.series_tag,
                total=character_count,
            )

            def on_progress(payload: dict[str, object]) -> None:
                self._update_job(
                    job_id,
                    status="running",
                    phase=payload.get("phase", "extracting"),
                    message=payload.get("message", ""),
                    current=payload.get("current", 0),
                    total=payload.get("total", 0),
                )
                # 체크포인트: 일시정지 요청 시 여기서 블록
                self._check_pause(job_id)

            service = AppearanceService(db)
            result = service.extract_for_series(series, progress_callback=on_progress)

            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                message=f"완료: {result.updated}/{result.processed}명 외형 태그 갱신",
                updated=result.updated,
                current=result.processed,
                total=result.processed,
                finished_at=_utc_now(),
            )
        except _PauseCancelledError:
            # 일시정지 중 취소됨
            return
        except DanbooruAuthError as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="Danbooru 인증 실패",
                error=str(exc),
                finished_at=_utc_now(),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="외형 태그 추출 중 오류 발생",
                error=str(exc),
                finished_at=_utc_now(),
            )

    def _finish_job(self, job_id: str, series_id: int) -> None:
        with self._lock:
            active_job_id = self._active_by_series.get(series_id)
            if active_job_id == job_id:
                self._active_by_series.pop(series_id, None)
            self._running_job_ids.discard(job_id)
            self._running_count = max(0, self._running_count - 1)

        self._dispatch_next()


series_job_manager = SeriesJobManager()
collect_job_manager = series_job_manager
