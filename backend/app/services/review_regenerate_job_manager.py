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
from app.models.global_character import GlobalCharacter
from app.services.generation_service import GenerationService
from app.services.review_catalog_serializer import to_catalog_item, to_catalog_item_global
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
    scope: str = "series"
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
    """시리즈(Character) 재생성과 캐릭터 목록(GlobalCharacter) 재생성을 하나의 큐로
    직렬 처리한다. 두 테이블의 id 공간이 서로 겹칠 수 있으므로 활성 작업 추적은
    반드시 (scope, character_id) 조합으로 구분해야 한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, ReviewRegenerateJobState] = {}
        self._active_by_character: dict[tuple[str, int], str] = {}
        self._job_queue: deque[str] = deque()
        self._running = False
        self._lock = threading.Lock()
        self._needs_inter_character_gap = False
        # 재생성 큐가 완전히 빌 때까지 메인 생성 큐를 계속 일시정지 상태로 붙잡아둔다.
        # 작업 사이마다 재개하면 그 틈에 메인 큐가 NAIA를 선점해 순서가 뒤섞인다.
        self._paused_generation_job_ids: set[str] = set()

    def get_job(self, job_id: str) -> ReviewRegenerateJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_job_for_character(self, character_id: int, *, scope: str = "series") -> ReviewRegenerateJobState | None:
        with self._lock:
            job_id = self._active_by_character.get((scope, character_id))
            if not job_id:
                return None
            return self._jobs.get(job_id)

    def is_character_busy(self, character_id: int, *, scope: str = "series") -> bool:
        job = self.get_active_job_for_character(character_id, scope=scope)
        return bool(job and job.status in {"queued", "running"})

    def list_visible_jobs(self, *, limit: int = 30) -> list[ReviewRegenerateJobState]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def dismiss_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"completed", "failed"}:
                return False
            del self._jobs[job_id]
            return True

    def _enqueue(
        self,
        character_id: int,
        *,
        prompt: str,
        gender: str | None,
        scope: str,
        character_tag: str,
        series_tag: str,
        images_per_character: int,
    ) -> ReviewRegenerateJobState:
        with self._lock:
            existing_job_id = self._active_by_character.get((scope, character_id))
            if existing_job_id:
                existing = self._jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing

        job = ReviewRegenerateJobState(
            job_id=str(uuid.uuid4()),
            character_id=character_id,
            character_tag=character_tag,
            series_tag=series_tag,
            scope=scope,
            prompt=prompt.strip(),
            gender=gender,
            total=images_per_character,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._active_by_character[(scope, character_id)] = job.job_id
            self._job_queue.append(job.job_id)
            self._refresh_queue_messages()

        self._dispatch_next()
        return job

    def enqueue(self, character_id: int, *, prompt: str, gender: str | None) -> ReviewRegenerateJobState:
        """시리즈 기반(Character) 재생성."""
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

            return self._enqueue(
                character_id,
                prompt=prompt,
                gender=gender,
                scope="series",
                character_tag=character.character_tag,
                series_tag=character.series.series_tag if character.series else "",
                images_per_character=service.get_images_per_character(),
            )
        finally:
            db.close()

    def enqueue_global(self, global_character_id: int, *, prompt: str, gender: str | None) -> ReviewRegenerateJobState:
        """캐릭터 목록(GlobalCharacter) 재생성. 시리즈 재생성과 id 공간이 다르므로
        절대 `enqueue()`(series 전용)로 대체 호출하면 안 된다."""
        db = SessionLocal()
        try:
            service = GenerationService(db)
            status = service.naia_status()
            if not status.get("ready"):
                raise ValueError(str(status.get("message") or "NAIA가 준비되지 않았습니다."))

            character = db.query(GlobalCharacter).filter(GlobalCharacter.id == global_character_id).first()
            if not character:
                raise ValueError("Character not found")

            return self._enqueue(
                global_character_id,
                prompt=prompt,
                gender=gender,
                scope="global",
                character_tag=character.character_tag,
                series_tag="",
                images_per_character=service.get_images_per_character(),
            )
        finally:
            db.close()

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
            scope = job.scope
            needs_gap = self._needs_inter_character_gap

        # 메인 생성 큐(시리즈/캐릭터 목록)가 NAIA를 점유 중이면 재생성이 그 결과와
        # 뒤섞이지 않도록 먼저 일시정지시키고, 재생성이 끝나면 반드시 재개한다.
        from app.services.generation_job_manager import generation_job_manager

        paused_job_ids = generation_job_manager.pause_all_running()
        with self._lock:
            self._paused_generation_job_ids.update(paused_job_ids)
        if paused_job_ids:
            self._update_job(job_id, message="다른 생성 작업 일시정지 중...")

        # 메인 큐가 이미 NAIA로부터 이 캐릭터의 이미지를 받아 저장 대기 중일 수
        # 있다. 일시정지는 "다음 NAIA 요청 전"에만 걸리므로, 이미 받아온 이미지의
        # 저장(후처리)까지 끝나길 기다린 뒤에 지워야 stale 이미지가 섞이지 않는다.
        generation_job_manager.wait_for_pending_postprocess(scope, character_id)

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
                if scope == "global":
                    refreshed = service.regenerate_review_images_global(
                        character_id,
                        prompt_core=prompt,
                        gender=gender,
                        progress_callback=on_progress,
                    )
                    result = to_catalog_item_global(refreshed).model_dump()
                else:
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
                if self._active_by_character.get((scope, character_id)) == job_id:
                    self._active_by_character.pop((scope, character_id), None)
                self._running = False
                self._refresh_queue_messages()
                # 대기 중인 재생성 작업이 하나라도 남아 있으면 메인 생성 큐를 재개하지
                # 않는다. 큐가 완전히 비었을 때만 모아둔 작업들을 한 번에 재개한다.
                has_pending = any(
                    (queued := self._jobs.get(queued_id)) is not None and queued.status == "queued"
                    for queued_id in self._job_queue
                )
                jobs_to_resume: list[str] = []
                if not has_pending:
                    jobs_to_resume = list(self._paused_generation_job_ids)
                    self._paused_generation_job_ids.clear()
            if jobs_to_resume:
                generation_job_manager.resume_jobs(jobs_to_resume)
            self._dispatch_next()


review_regenerate_job_manager = ReviewRegenerateJobManager()
