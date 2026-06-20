from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.character import Character
from app.models.series import Series
from app.services.collect_job_manager import series_job_manager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PipelineState:
    status: str = "idle"  # idle | running | stopping | completed | failed
    phase: str | None = None  # "collecting" | "extracting"
    collect_total: int = 0
    collect_done: int = 0
    collect_failed: int = 0
    extract_total: int = 0
    extract_done: int = 0
    extract_failed: int = 0
    current_series_tag: str | None = None
    current_job_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[str] = field(default_factory=list)


class PipelineManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = PipelineState()
        self._stop_event = threading.Event()

    def get_state(self) -> PipelineState:
        with self._lock:
            s = self._state
            return PipelineState(
                status=s.status,
                phase=s.phase,
                collect_total=s.collect_total,
                collect_done=s.collect_done,
                collect_failed=s.collect_failed,
                extract_total=s.extract_total,
                extract_done=s.extract_done,
                extract_failed=s.extract_failed,
                current_series_tag=s.current_series_tag,
                current_job_message=s.current_job_message,
                started_at=s.started_at,
                finished_at=s.finished_at,
                errors=list(s.errors),
            )

    def start(self) -> bool:
        with self._lock:
            if self._state.status in {"running", "stopping"}:
                return False
            self._state = PipelineState(status="running", started_at=_utc_now())
            self._stop_event.clear()

        thread = threading.Thread(target=self._run, daemon=True, name="pipeline-manager")
        thread.start()
        return True

    def stop(self) -> bool:
        with self._lock:
            if self._state.status != "running":
                return False
            self._state.status = "stopping"
        self._stop_event.set()
        return True

    def _update(self, **fields: object) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._state, key, value)

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()

    def _run(self) -> None:
        try:
            self._run_collect_phase()
            if not self._should_stop():
                self._run_extract_phase()

            with self._lock:
                self._state.status = "stopped" if self._stop_event.is_set() else "completed"
                self._state.finished_at = _utc_now()
                self._state.current_series_tag = None
                self._state.current_job_message = None
                self._state.phase = None
        except Exception as exc:
            with self._lock:
                self._state.status = "failed"
                self._state.finished_at = _utc_now()
                self._state.errors.append(str(exc))
                self._state.current_series_tag = None
                self._state.current_job_message = None
                self._state.phase = None

    def _get_collect_targets(self) -> list[tuple[int, str]]:
        db = SessionLocal()
        try:
            rows = (
                db.query(Series.id, Series.series_tag)
                .filter(
                    Series.parent_series_id.is_(None),
                    Series.status.in_(["pending", "collecting"]),
                )
                .order_by(Series.priority.asc(), Series.post_count.desc(), Series.id.asc())
                .all()
            )
            return [(row.id, row.series_tag) for row in rows]
        finally:
            db.close()

    def _get_extract_targets(self) -> list[tuple[int, str]]:
        db = SessionLocal()
        try:
            rows = (
                db.query(Series.id, Series.series_tag)
                .filter(
                    Series.parent_series_id.is_(None),
                    Series.status == "collected",
                )
                .order_by(Series.priority.asc(), Series.post_count.desc(), Series.id.asc())
                .all()
            )
            eligible = []
            for row in rows:
                char_count = db.query(Character).filter(Character.series_id == row.id).count()
                if char_count > 0:
                    eligible.append((row.id, row.series_tag))
            return eligible
        finally:
            db.close()

    def _is_still_pending(self, series_id: int) -> bool:
        db = SessionLocal()
        try:
            row = (
                db.query(Series.status, Series.parent_series_id)
                .filter(Series.id == series_id)
                .first()
            )
            if not row:
                return False
            return row.status in ("pending", "collecting") and row.parent_series_id is None
        finally:
            db.close()

    def _is_still_collected(self, series_id: int) -> bool:
        db = SessionLocal()
        try:
            row = (
                db.query(Series.status, Series.parent_series_id)
                .filter(Series.id == series_id)
                .first()
            )
            if not row:
                return False
            return row.status == "collected" and row.parent_series_id is None
        finally:
            db.close()

    def _run_phase(
        self,
        phase: str,
        targets: list[tuple[int, str]],
        *,
        is_still_eligible,
        submit_job,
        done_attr: str,
        failed_attr: str,
        total_attr: str,
    ) -> None:
        self._update(**{total_attr: len(targets), "phase": phase})

        # 전체 작업을 한번에 제출해 job manager의 max_concurrent 슬롯을 최대한 활용
        job_map: dict[str, str] = {}  # job_id → series_tag

        for series_id, series_tag in targets:
            if self._should_stop():
                break
            if not is_still_eligible(series_id):
                with self._lock:
                    prev = getattr(self._state, total_attr)
                    setattr(self._state, total_attr, max(0, prev - 1))
                continue
            try:
                job = submit_job(series_id)
                job_map[job.job_id] = series_tag
            except Exception as exc:
                with self._lock:
                    getattr(self._state, failed_attr)
                    setattr(self._state, failed_attr, getattr(self._state, failed_attr) + 1)
                    self._state.errors.append(f"[{phase}] {series_tag}: {exc}")

        # 제출된 모든 작업이 완료될 때까지 대기
        remaining: set[str] = set(job_map)
        while remaining:
            time.sleep(1)
            finished: set[str] = set()

            for job_id in remaining:
                current_job = series_job_manager.get_job(job_id)
                if not current_job:
                    finished.add(job_id)
                    continue
                if current_job.status == "running":
                    self._update(
                        current_series_tag=job_map[job_id],
                        current_job_message=current_job.message,
                    )
                if current_job.status in {"completed", "failed", "cancelled"}:
                    finished.add(job_id)
                    with self._lock:
                        if current_job.status == "completed":
                            setattr(self._state, done_attr, getattr(self._state, done_attr) + 1)
                        else:
                            setattr(self._state, failed_attr, getattr(self._state, failed_attr) + 1)
                            if current_job.error:
                                self._state.errors.append(f"[{phase}] {job_map[job_id]}: {current_job.error}")

            remaining -= finished

            if self._should_stop():
                # 아직 대기 중인 작업은 취소, 실행 중인 작업은 자연 완료 대기
                for job_id in list(remaining):
                    current_job = series_job_manager.get_job(job_id)
                    if current_job and current_job.status == "queued":
                        if series_job_manager.cancel_job(job_id):
                            with self._lock:
                                setattr(self._state, total_attr, max(0, getattr(self._state, total_attr) - 1))
                            remaining.discard(job_id)
                # 실행 중인 작업이 끝날 때까지 대기
                while remaining:
                    time.sleep(1)
                    still_running: set[str] = set()
                    for job_id in remaining:
                        current_job = series_job_manager.get_job(job_id)
                        if current_job and current_job.status in {"queued", "running"}:
                            still_running.add(job_id)
                        elif current_job and current_job.status in {"completed", "failed", "cancelled"}:
                            with self._lock:
                                if current_job.status == "completed":
                                    setattr(self._state, done_attr, getattr(self._state, done_attr) + 1)
                                else:
                                    setattr(self._state, failed_attr, getattr(self._state, failed_attr) + 1)
                    remaining = still_running
                break

    def _run_collect_phase(self) -> None:
        targets = self._get_collect_targets()
        self._run_phase(
            "collecting",
            targets,
            is_still_eligible=self._is_still_pending,
            submit_job=series_job_manager.start_series_collect,
            done_attr="collect_done",
            failed_attr="collect_failed",
            total_attr="collect_total",
        )

    def _run_extract_phase(self) -> None:
        targets = self._get_extract_targets()
        self._run_phase(
            "extracting",
            targets,
            is_still_eligible=self._is_still_collected,
            submit_job=series_job_manager.start_appearance_extract,
            done_attr="extract_done",
            failed_attr="extract_failed",
            total_attr="extract_total",
        )


pipeline_manager = PipelineManager()
