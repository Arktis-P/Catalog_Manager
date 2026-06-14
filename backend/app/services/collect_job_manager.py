from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.danbooru.client import DanbooruAuthError
from app.models.series import Series
from app.services.character_service import CharacterService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CollectJobState:
    job_id: str
    series_id: int
    series_tag: str
    status: str = "queued"
    phase: str = "queued"
    message: str = "대기 중..."
    current: int = 0
    total: int = 0
    discovered: int = 0
    created: int = 0
    skipped_existing: int = 0
    error: str | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class CollectJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, CollectJobState] = {}
        self._active_by_series: dict[int, str] = {}
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> CollectJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_job_for_series(self, series_id: int) -> CollectJobState | None:
        with self._lock:
            job_id = self._active_by_series.get(series_id)
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[CollectJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def start_series_collect(self, series_id: int) -> CollectJobState:
        with self._lock:
            existing_job_id = self._active_by_series.get(series_id)
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing

            job = CollectJobState(
                job_id=str(uuid.uuid4()),
                series_id=series_id,
                series_tag="",
            )
            self._jobs[job.job_id] = job
            self._active_by_series[series_id] = job.job_id

        thread = threading.Thread(
            target=self._run_series_collect,
            args=(job.job_id, series_id),
            daemon=True,
            name=f"collect-series-{series_id}",
        )
        thread.start()
        return job

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

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
            with self._lock:
                active_job_id = self._active_by_series.get(series_id)
                if active_job_id == job_id:
                    self._active_by_series.pop(series_id, None)


collect_job_manager = CollectJobManager()
