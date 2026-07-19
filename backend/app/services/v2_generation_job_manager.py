from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.services.db_write_queue import job_write_context
from app.services.generation_service import GenerationService
from app.services.v2_generation_pipeline import V2GenerationPipeline, V2PipelineCancelled


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _PauseCancelledError(BaseException):
    """Raised when a paused V2 job is cancelled before it resumes."""


@dataclass
class V2GenerationJobState:
    job_id: str
    kind: str = "generate"
    status: str = "queued"
    phase: str = "queued"
    message: str = "V2 자동 생성 대기 중..."
    current: int = 0
    total: int = 0
    completed: int = 0
    failed: int = 0
    character_tag: str = ""
    current_character_tag: str = ""
    character_id: int | None = None
    generation_status: str | None = None
    generation_attempts: int = 0
    total_generation_attempts: int = 0
    prompt_variant_attempts: dict[str, int] = field(default_factory=dict)
    image_id: int | None = None
    quality_status: str | None = None
    quality_reasons: list[str] = field(default_factory=list)
    identity_status: str | None = None
    identity_reasons: list[str] = field(default_factory=list)
    is_provisional: bool | None = None
    last_failure_reason: str | None = None
    errors: list[dict[str, object]] = field(default_factory=list)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class V2GenerationJobManager:
    """V2 자동 생성 배치를 하나씩 직렬 실행하고 진행률·취소를 관리한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, V2GenerationJobState] = {}
        self._queue: deque[str] = deque()
        self._arguments: dict[str, tuple[list[int] | None, bool, str | None, int | None]] = {}
        self._cancelled: set[str] = set()
        self._regenerating_character_ids: set[int] = set()
        self._active_job_id: str | None = None
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()
        self._auto_paused_jobs: set[str] = set()

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
            self._arguments[job.job_id] = (
                list(character_ids) if character_ids is not None else None,
                rerun,
                None,
                None,
            )
        self._dispatch_next()
        return job

    def start_regeneration(
        self,
        character_id: int,
        *,
        base_prompt: str | None = None,
        character_tag: str | None = None,
    ) -> V2GenerationJobState | None:
        job = V2GenerationJobState(
            job_id=str(uuid.uuid4()),
            kind="regenerate",
            message="V2 수동 재생성 대기 중...",
            total=1,
            character_id=character_id,
            character_tag=character_tag or "",
            current_character_tag=character_tag or "",
        )
        active_job_id_to_pause: str | None = None
        with self._lock:
            if character_id in self._regenerating_character_ids:
                return None
            self._regenerating_character_ids.add(character_id)
            self._jobs[job.job_id] = job
            self._queue.appendleft(job.job_id)
            self._arguments[job.job_id] = ([character_id], True, base_prompt, character_id)
            active_job = self._jobs.get(self._active_job_id or "")
            if active_job and active_job.kind == "generate" and active_job.status == "running":
                active_job_id_to_pause = active_job.job_id
                self._auto_paused_jobs.add(active_job.job_id)
                active_job.message = "일시정지 요청됨(자동) · 현재 캐릭터 완료 후 V2 재생성 우선 실행"
        if active_job_id_to_pause is not None:
            self.pause(active_job_id_to_pause)
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

    def pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False
        with self._pause_cond:
            self._paused_jobs.add(job_id)
        return True

    def resume(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"paused", "running"}:
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
        should_dispatch_next = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "paused"
                job.phase = "paused"
                if job_id in self._auto_paused_jobs:
                    job.message = "일시정지됨(자동) · V2 재생성 완료 후 이어서 진행"
                    if self._active_job_id == job_id:
                        self._active_job_id = None
                        should_dispatch_next = True
                else:
                    job.message = "일시정지됨 · 재개 시 이어서 진행"
                job.current_character_tag = ""
        if should_dispatch_next:
            self._dispatch_next()
        with self._pause_cond:
            while job_id in self._paused_jobs:
                self._pause_cond.wait(timeout=2.0)
        while True:
            with self._lock:
                active_job = self._jobs.get(self._active_job_id or "")
                if self._active_job_id in {None, job_id} or (
                    active_job is not None and active_job.status in {"completed", "failed", "cancelled"}
                ):
                    self._active_job_id = job_id
                    break
            time.sleep(0.05)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                raise _PauseCancelledError()
            job.status = "running"
            job.phase = "generating"
            job.message = "작업 재개됨"
            self._auto_paused_jobs.discard(job_id)
        return True

    def cancel(self, job_id: str) -> bool:
        resume_auto_paused = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running", "paused"}:
                return False
            was_queued = job.status == "queued"
            self._cancelled.add(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "사용자가 취소했습니다."
            job.finished_at = _utc_now()
            if was_queued:
                arguments = self._arguments.pop(job_id, None)
                if arguments is not None and arguments[3] is not None:
                    self._regenerating_character_ids.discard(arguments[3])
                    resume_auto_paused = not self._has_pending_regeneration_locked()
        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()
        if resume_auto_paused:
            self._resume_auto_paused_jobs()
        return True

    def _has_pending_regeneration_locked(self) -> bool:
        active = self._jobs.get(self._active_job_id or "")
        if active is not None and active.kind == "regenerate" and active.status in {"queued", "running", "paused"}:
            return True
        for queued_job_id in self._queue:
            queued_job = self._jobs.get(queued_job_id)
            if queued_job is not None and queued_job.kind == "regenerate" and queued_job.status == "queued":
                return True
        return False

    def _resume_auto_paused_jobs(self) -> None:
        with self._lock:
            job_ids = list(self._auto_paused_jobs)
        for paused_job_id in job_ids:
            self.resume(paused_job_id)
            with self._lock:
                self._auto_paused_jobs.discard(paused_job_id)

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
        selected: tuple[str, list[int] | None, bool, str | None, int | None] | None = None
        with self._lock:
            if self._active_job_id is not None:
                return
            while self._queue:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                character_ids, rerun, base_prompt, regeneration_character_id = self._arguments.pop(
                    job_id, (None, False, None, None)
                )
                self._active_job_id = job_id
                selected = (job_id, character_ids, rerun, base_prompt, regeneration_character_id)
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

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        parsed = json.loads(value)
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    def _run(
        self,
        job_id: str,
        character_ids: list[int] | None,
        rerun: bool,
        base_prompt: str | None,
        regeneration_character_id: int | None,
    ) -> None:
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
                if regeneration_character_id is not None and not characters:
                    self._update(
                        job_id,
                        status="failed",
                        phase="failed",
                        message="Character not found",
                        failed=1,
                        finished_at=_utc_now(),
                    )
                    return
                self._update(
                    job_id,
                    status="running",
                    phase="generating",
                    message=(
                        f"V2 재생성 시작 · {characters[0].character_tag}"
                        if regeneration_character_id is not None and characters
                        else f"V2 자동 생성 시작 · {len(characters)}명"
                    ),
                    total=len(characters),
                )
                pipeline = V2GenerationPipeline(db)
                for index, character in enumerate(characters, start=1):
                    if self._is_cancelled(job_id):
                        break
                    self._check_pause(job_id)
                    self._update(
                        job_id,
                        current=index - 1,
                        current_character_tag=character.character_tag,
                        message=f"{character.character_tag} 처리 중 ({index}/{len(characters)})",
                    )
                    try:
                        result = pipeline.run_character(
                            character.id,
                            base_prompt=(
                                base_prompt if character.id == regeneration_character_id else None
                            ),
                            should_cancel=lambda: self._is_cancelled(job_id),
                        )
                        image = db.get(GlobalCharacterImage, result.image_id) if result.image_id else None
                        self._increment(job_id, completed=1)
                        self._update(
                            job_id,
                            current=index,
                            message=f"{character.character_tag}: {result.generation_status}",
                            generation_status=result.generation_status,
                            generation_attempts=result.generation_attempts,
                            total_generation_attempts=character.total_generation_attempts,
                            prompt_variant_attempts=json.loads(
                                character.prompt_variant_attempts or "{}"
                            ),
                            image_id=result.image_id,
                            quality_status=image.quality_status if image else None,
                            quality_reasons=self._json_list(image.quality_reasons) if image else [],
                            identity_status=image.identity_status if image else None,
                            identity_reasons=self._json_list(image.identity_reasons) if image else [],
                            is_provisional=image.is_provisional if image else None,
                            last_failure_reason=character.last_failure_reason,
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

                self._check_pause(job_id)
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
        except _PauseCancelledError:
            return
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
                if regeneration_character_id is not None:
                    self._regenerating_character_ids.discard(regeneration_character_id)
                if self._active_job_id == job_id:
                    self._active_job_id = None
                should_resume_auto_paused = (
                    regeneration_character_id is not None and not self._has_pending_regeneration_locked()
                )
            with self._pause_cond:
                self._paused_jobs.discard(job_id)
                self._pause_cond.notify_all()
            if should_resume_auto_paused:
                self._resume_auto_paused_jobs()
            self._dispatch_next()


v2_generation_job_manager = V2GenerationJobManager()
