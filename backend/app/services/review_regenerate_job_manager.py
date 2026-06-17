from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.naia.generation_runner import wait_between_naia_generations
from app.models.character import Character
from app.services.generation_service import GenerationService
from app.services.review_catalog_serializer import to_catalog_item
from sqlalchemy.orm import joinedload

ProgressCallback = Callable[[dict[str, object]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReviewRegenerateJobState:
    job_id: str
    character_id: int
    character_tag: str
    prompt: str
    gender: str | None = None
    series_tag: str = ""
    status: str = "queued"
    phase: str = "queued"
    message: str = "재생성 대기 중..."
    current: int = 0
    total: int = 0
    error: str | None = None
    result: dict[str, object] | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class ReviewRegenerateJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ReviewRegenerateJobState] = {}
        self._active_by_character: dict[int, str] = {}
        self._job_queue: deque[str] = deque()
        self._running = False
        self._lock = threading.Lock()
        self._needs_inter_character_gap = False

    def get_job(self, job_id: str) -> ReviewRegenerateJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_job_for_character(self, character_id: int) -> ReviewRegenerateJobState | None:
        with self._lock:
            job_id = self._active_by_character.get(character_id)
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def is_character_busy(self, character_id: int) -> bool:
        job = self.get_active_job_for_character(character_id)
        return bool(job and job.status in {"queued", "running"})

    def list_visible_jobs(self, *, limit: int = 30) -> list[ReviewRegenerateJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def enqueue(self, character_id: int, *, prompt: str, gender: str | None) -> ReviewRegenerateJobState:
        with self._lock:
            existing_job_id = self._active_by_character.get(character_id)
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing

        db = SessionLocal()
        try:
            service = GenerationService(db)
            status = service.naia_status()
            if not status.get("ready"):
                raise ValueError(str(status.get("message") or "NAIA가 준비되지 않았습니다."))

            character = (
                db.query(Character)
                .options(joinedload(Character.series))
                .filter(Character.id == character_id)
                .first()
            )
            if not character:
                raise ValueError("Character not found")

            job = ReviewRegenerateJobState(
                job_id=str(uuid.uuid4()),
                character_id=character_id,
                character_tag=character.character_tag,
                series_tag=character.series.series_tag if character.series else "",
                prompt=prompt.strip(),
                gender=gender,
                total=service.get_images_per_character(),
            )
            with self._lock:
                self._jobs[job.job_id] = job
                self._active_by_character[character_id] = job.job_id
                self._job_queue.append(job.job_id)
                self._refresh_queue_messages()
        finally:
            db.close()

        self._dispatch_next()
        return job

    def _refresh_queue_messages(self) -> None:
        queue_index = 0
        for queued_job_id in self._job_queue:
            queued_job = self._jobs.get(queued_job_id)
            if not queued_job or queued_job.status != "queued":
                continue
            queue_index += 1
            if queue_index == 1 and not self._running:
                queued_job.message = "재생성 곧 시작"
            else:
                ahead = queue_index - (0 if not self._running else 1)
                queued_job.message = f"재생성 대기 중 · 앞에 {max(0, ahead)}건"

    def _dispatch_next(self) -> None:
        job_id: str | None = None
        with self._lock:
            if self._running:
                return
            while self._job_queue:
                candidate_id = self._job_queue.popleft()
                candidate = self._jobs.get(candidate_id)
                if candidate and candidate.status == "queued":
                    job_id = candidate_id
                    self._running = True
                    break

        if not job_id:
            return

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"review-regenerate-{job_id[:8]}",
        )
        thread.start()

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                self._running = False
                return
            prompt = job.prompt
            gender = job.gender
            character_id = job.character_id
            needs_gap = self._needs_inter_character_gap

        try:
            if needs_gap:
                self._update_job(job_id, message="다음 캐릭터 재생성 전 NAIA 대기 중...")
                wait_between_naia_generations()

            def on_progress(payload: dict[str, object]) -> None:
                self._update_job(
                    job_id,
                    status="running",
                    phase=payload.get("phase", "running"),
                    message=payload.get("message", ""),
                    current=payload.get("current", 0),
                    total=payload.get("total", 0),
                )

            self._update_job(
                job_id,
                status="running",
                phase="starting",
                message=f"{job.character_tag} 재생성 시작",
            )

            db = SessionLocal()
            try:
                service = GenerationService(db)
                refreshed = service.regenerate_review_images(
                    character_id,
                    prompt_core=prompt,
                    gender=gender,
                    progress_callback=on_progress,
                )
                result = to_catalog_item(refreshed).model_dump()
                with self._lock:
                    current_job = self._jobs.get(job_id)
                    total = current_job.total if current_job else len(result.get("images", []))
                self._update_job(
                    job_id,
                    status="completed",
                    phase="completed",
                    message=f"완료: 이미지 {len(result.get('images', []))}장",
                    current=total,
                    result=result,
                    finished_at=_utc_now(),
                )
            finally:
                db.close()
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="재생성 실패",
                error=str(exc),
                finished_at=_utc_now(),
            )
        finally:
            with self._lock:
                self._needs_inter_character_gap = True
                if self._active_by_character.get(character_id) == job_id:
                    self._active_by_character.pop(character_id, None)
                self._running = False
                self._refresh_queue_messages()
            self._dispatch_next()


review_regenerate_job_manager = ReviewRegenerateJobManager()
