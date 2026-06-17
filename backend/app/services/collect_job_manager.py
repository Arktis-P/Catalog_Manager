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
from app.services.settings_service import SettingsService

JOB_TYPE_CHARACTER_COLLECT = "character_collect"
JOB_TYPE_APPEARANCE_EXTRACT = "appearance_extract"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._running_count = 0
        self._lock = threading.Lock()

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

    def get_active_job_for_series(self, series_id: int) -> SeriesJobState | None:
        with self._lock:
            job_id = self._active_by_series.get(series_id)
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[SeriesJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def start_series_collect(self, series_id: int) -> SeriesJobState:
        return self._enqueue(series_id, JOB_TYPE_CHARACTER_COLLECT)

    def start_appearance_extract(self, series_id: int) -> SeriesJobState:
        return self._enqueue(series_id, JOB_TYPE_APPEARANCE_EXTRACT)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return False

            self._job_queue = deque(queued_id for queued_id in self._job_queue if queued_id != job_id)

            task_label = "수집" if job.job_type == JOB_TYPE_CHARACTER_COLLECT else "외형 추출"
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = f"{task_label} 대기 취소됨"
            job.finished_at = _utc_now()

            if self._active_by_series.get(job.series_id) == job_id:
                self._active_by_series.pop(job.series_id, None)

            self._refresh_queue_messages()

        self._dispatch_next()
        return True

    def _enqueue(self, series_id: int, job_type: str) -> SeriesJobState:
        with self._lock:
            existing_job_id = self._active_by_series.get(series_id)
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing

            job = SeriesJobState(
                job_id=str(uuid.uuid4()),
                series_id=series_id,
                series_tag="",
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
        finally:
            db.close()
            self._finish_job(job_id, series_id)

    def _run_appearance_extract(self, job_id: str, series_id: int) -> None:
        db = SessionLocal()
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
        finally:
            db.close()
            self._finish_job(job_id, series_id)

    def _finish_job(self, job_id: str, series_id: int) -> None:
        with self._lock:
            active_job_id = self._active_by_series.get(series_id)
            if active_job_id == job_id:
                self._active_by_series.pop(series_id, None)
            self._running_count = max(0, self._running_count - 1)

        self._dispatch_next()


series_job_manager = SeriesJobManager()
collect_job_manager = series_job_manager
