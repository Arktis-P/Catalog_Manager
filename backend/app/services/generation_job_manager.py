from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.integrations.naia.client import NaiaClient
from app.integrations.naia.generation_runner import (
    generate_and_fetch_image,
    wait_between_naia_generations,
)
from app.models.character import Character
from app.models.generation_job import GenerationJob
from app.models.series import Series
from app.services.generation_service import GenerationService

JOB_TYPE_IMAGE_GENERATION = "image_generation"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GenerationBatchState:
    job_id: str
    series_id: int
    series_tag: str
    queue_id: str
    job_type: str = JOB_TYPE_IMAGE_GENERATION
    status: str = "queued"
    phase: str = "queued"
    message: str = "대기 중..."
    current: int = 0
    total: int = 0
    completed: int = 0
    failed: int = 0
    prompt_level: int = 1
    current_character_tag: str = ""
    last_image_path: str | None = None
    auto_pass: int = 0
    auto_warning: int = 0
    auto_reject: int = 0
    error: str | None = None
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class GenerationJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, GenerationBatchState] = {}
        self._active_by_series: dict[int, str] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> GenerationBatchState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_job_for_series(self, series_id: int) -> GenerationBatchState | None:
        with self._lock:
            job_id = self._active_by_series.get(series_id)
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def list_visible_jobs(self, *, limit: int = 20) -> list[GenerationBatchState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"queued", "running"}:
                return False
            self._cancelled.add(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "사용자가 취소했습니다."
            job.finished_at = _utc_now()
            self._active_by_series.pop(job.series_id, None)
            return True

    def start_generation(
        self,
        series_id: int,
        *,
        character_ids: list[int] | None,
        prompt_level: int,
        require_confirmed: bool = True,
    ) -> GenerationBatchState:
        with self._lock:
            existing_job_id = self._active_by_series.get(series_id)
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing

            job = GenerationBatchState(
                job_id=str(uuid.uuid4()),
                series_id=series_id,
                series_tag="",
                queue_id="",
                prompt_level=prompt_level,
            )
            self._jobs[job.job_id] = job
            self._active_by_series[series_id] = job.job_id

        thread = threading.Thread(
            target=self._run_generation,
            args=(job.job_id, series_id, character_ids, prompt_level, require_confirmed),
            daemon=True,
            name=f"generation-{series_id}",
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

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _run_generation(
        self,
        job_id: str,
        series_id: int,
        character_ids: list[int] | None,
        prompt_level: int,
        require_confirmed: bool,
    ) -> None:
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

            service = GenerationService(db)
            status = service.naia_status()
            if not status.get("ready"):
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message=str(status.get("message") or "NAIA 연결 실패"),
                    error=str(status.get("message") or "NAIA not ready"),
                    finished_at=_utc_now(),
                )
                return

            self._update_job(
                job_id,
                status="running",
                phase="preparing",
                message=f"{series.series_tag} 생성 큐 준비 중",
                series_tag=series.series_tag,
            )

            queue_payload = service.prepare_queue(
                series_id,
                character_ids=character_ids,
                prompt_level=prompt_level,
                require_confirmed=require_confirmed,
            )
            images_per_character = service.get_images_per_character()
            jobs = service.create_generation_jobs(queue_payload, images_per_character=images_per_character)
            if not jobs:
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message="생성 작업을 만들 수 없습니다.",
                    error="No generation jobs created",
                    finished_at=_utc_now(),
                )
                return

            client = NaiaClient(str(status.get("base_url") or service.get_naia_base_url()))
            known_history_ids = {
                str(item.get("history_id") or "")
                for item in client.list_history(page=0, per_page=20).get("images", [])
                if isinstance(item, dict)
            }
            known_history_ids.discard("")

            self._update_job(
                job_id,
                status="running",
                phase="generating",
                queue_id=str(queue_payload.get("queue_id") or ""),
                message=f"{series.series_tag} 이미지 생성 시작",
                total=len(jobs),
                current=0,
            )

            completed = 0
            failed = 0
            auto_pass = 0
            auto_warning = 0
            auto_reject = 0
            for index, generation_job in enumerate(jobs, start=1):
                if self._is_cancelled(job_id):
                    return

                if index > 1:
                    wait_between_naia_generations()

                character = db.query(Character).filter(Character.id == generation_job.character_id).first()
                if not character:
                    failed += 1
                    service.mark_job_failed(generation_job, "Character not found")
                    continue

                self._update_job(
                    job_id,
                    current=index - 1,
                    current_character_tag=character.character_tag,
                    message=f"{character.character_tag} 생성 중 ({index}/{len(jobs)})",
                )

                try:
                    def _on_retry(attempt: int, exc: Exception) -> None:
                        self._update_job(
                            job_id,
                            message=(
                                f"{character.character_tag} NAIA 오류, 동일 프롬프트 재시도 "
                                f"({attempt}회차): {exc}"
                            ),
                        )

                    image_bytes, _ = generate_and_fetch_image(
                        client,
                        prompt=generation_job.prompt,
                        negative_prompt=generation_job.negative_prompt or "",
                        known_history_ids=known_history_ids,
                        on_retry=_on_retry,
                    )
                    image = service.import_generated_image(
                        character=character,
                        generation_job=generation_job,
                        image_bytes=image_bytes,
                    )
                    completed += 1
                    if image.auto_status == "pass":
                        auto_pass += 1
                    elif image.auto_status == "warning":
                        auto_warning += 1
                    elif image.auto_status == "reject_candidate":
                        auto_reject += 1
                    self._update_job(
                        job_id,
                        completed=completed,
                        failed=failed,
                        auto_pass=auto_pass,
                        auto_warning=auto_warning,
                        auto_reject=auto_reject,
                        current=index,
                        last_image_path=image.image_path,
                        message=f"{character.character_tag} 저장 · 자동검사 {image.auto_status} ({index}/{len(jobs)})",
                    )
                except Exception as exc:
                    failed += 1
                    service.mark_job_failed(generation_job, str(exc))
                    self._update_job(
                        job_id,
                        completed=completed,
                        failed=failed,
                        current=index,
                        message=f"{character.character_tag} 실패: {exc}",
                    )

            summary = f"완료: {completed}장 저장 · 실패 {failed}"
            if completed:
                summary += f" · 자동검사 pass {auto_pass} / warning {auto_warning} / reject {auto_reject}"
            final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "completed")
            self._update_job(
                job_id,
                status=final_status,
                phase="completed" if completed else "failed",
                message=summary,
                completed=completed,
                failed=failed,
                auto_pass=auto_pass,
                auto_warning=auto_warning,
                auto_reject=auto_reject,
                current=len(jobs),
                finished_at=_utc_now(),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                message="이미지 생성 중 오류 발생",
                error=str(exc),
                finished_at=_utc_now(),
            )
        finally:
            db.close()
            with self._lock:
                active_job_id = self._active_by_series.get(series_id)
                if active_job_id == job_id:
                    self._active_by_series.pop(series_id, None)


generation_job_manager = GenerationJobManager()
