from __future__ import annotations

import threading
import uuid
from collections import defaultdict, deque
from concurrent.futures import Future, ThreadPoolExecutor
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
from app.models.global_character import GlobalCharacter
from app.models.global_character_generation_job import GlobalCharacterGenerationJob
from app.models.image import Image
from app.models.global_character_image import GlobalCharacterImage
from app.models.series import Series
from app.services.generation_prompt_builder import build_full_prompt
from app.services.generation_service import GenerationService
from app.services.series_generation_status import (
    finalize_series_after_batch,
    mark_series_generating,
    queue_covers_all_eligible_characters,
    restore_series_status,
)

_MAX_PROMPT_LEVEL = 5
_MAX_ESCALATIONS = 2

# 저장/자동검사(WD 태거 등 외부 호출 포함)를 NAIA 다음 요청과 겹쳐서 실행하기 위한 후처리 전용 풀.
# NAIA 호출 자체는 여전히 순차적이지만, 후처리는 다음 이미지 생성 요청을 막지 않는다.
_POSTPROCESS_WORKERS = 2

JOB_TYPE_IMAGE_GENERATION = "image_generation"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _postprocess_character_image(character_id: int, generation_job_id: int, image_bytes: bytes) -> Image:
    """시리즈(Character) 이미지 저장 + 자동검사. 메인 생성 스레드와 별도 세션/스레드에서 실행된다."""
    db = SessionLocal()
    try:
        character = db.query(Character).filter(Character.id == character_id).first()
        generation_job = db.query(GenerationJob).filter(GenerationJob.id == generation_job_id).first()
        if not character or not generation_job:
            raise ValueError("Character 또는 GenerationJob을 찾을 수 없습니다.")
        service = GenerationService(db)
        return service.import_generated_image(
            character=character,
            generation_job=generation_job,
            image_bytes=image_bytes,
        )
    finally:
        db.close()


def _postprocess_global_character_image(
    character_id: int, generation_job_id: int, image_bytes: bytes
) -> GlobalCharacterImage:
    """캐릭터 목록(GlobalCharacter) 이미지 저장 + 자동검사. 메인 생성 스레드와 별도 세션/스레드에서 실행된다."""
    db = SessionLocal()
    try:
        character = db.query(GlobalCharacter).filter(GlobalCharacter.id == character_id).first()
        generation_job = (
            db.query(GlobalCharacterGenerationJob)
            .filter(GlobalCharacterGenerationJob.id == generation_job_id)
            .first()
        )
        if not character or not generation_job:
            raise ValueError("GlobalCharacter 또는 GenerationJob을 찾을 수 없습니다.")
        service = GenerationService(db)
        return service.import_generated_image_global(
            character=character,
            generation_job=generation_job,
            image_bytes=image_bytes,
        )
    finally:
        db.close()


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
    status_before_generation: str = ""
    marks_series_generated: bool = False
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class GenerationJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, GenerationBatchState] = {}
        self._active_by_series: dict[int, str] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._pause_cond = threading.Condition(threading.Lock())
        self._paused_jobs: set[str] = set()
        # 캐릭터 목록(GlobalCharacter) 중심 생성: series 기반 생성과 완전히 독립된 큐.
        # 한 번에 하나만 실행하고, 진행 중일 때 새 요청은 대기열에서 기다린다.
        self._character_queue: deque[str] = deque()
        self._character_job_kwargs: dict[str, dict] = {}
        self._active_character_job: str | None = None
        self._postprocess_executor = ThreadPoolExecutor(
            max_workers=_POSTPROCESS_WORKERS, thread_name_prefix="gen-postprocess"
        )

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

    def pause_job(self, job_id: str) -> bool:
        """현재 실행 중인 이미지 생성 작업을 일시정지 요청."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return False
        with self._pause_cond:
            self._paused_jobs.add(job_id)
        return True

    def resume_job(self, job_id: str) -> bool:
        """일시정지된 이미지 생성 작업 재개."""
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
        """체크포인트. 일시정지 요청 시 재개될 때까지 블록. 취소되면 False 반환."""
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
            if job_id in self._cancelled:
                return False
            job = self._jobs.get(job_id)
            if job and job.status == "paused":
                job.status = "running"
                job.message = "작업 재개됨"

        return True

    def cancel_job(self, job_id: str) -> bool:
        was_paused = False
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"queued", "running", "paused"}:
                return False
            was_paused = job.status == "paused"
            self._cancelled.add(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "사용자가 취소했습니다."
            job.finished_at = _utc_now()
            series_id = job.series_id
            status_before = job.status_before_generation
            self._active_by_series.pop(series_id, None)

        if status_before and not was_paused:
            # paused 상태에서는 _run_generation 스레드가 restore를 처리
            db = SessionLocal()
            try:
                series = db.query(Series).filter(Series.id == series_id).first()
                if series:
                    restore_series_status(db, series, status_before)
            finally:
                db.close()

        # 일시정지 중인 스레드 깨우기
        with self._pause_cond:
            self._paused_jobs.discard(job_id)
            self._pause_cond.notify_all()

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
                if existing and existing.status in {"queued", "running", "paused"}:
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

    def start_character_generation(
        self,
        character_ids: list[int],
        *,
        prompt_level: int,
    ) -> GenerationBatchState:
        """캐릭터 목록(GlobalCharacter) 중심 이미지 생성. 이미 하나가 진행 중이면
        새 작업은 대기열에 올라가 있다가 이전 작업이 끝나면 이어서 시작된다."""
        with self._lock:
            job = GenerationBatchState(
                job_id=str(uuid.uuid4()),
                series_id=0,
                series_tag=f"캐릭터 {len(character_ids)}명",
                queue_id="",
                prompt_level=prompt_level,
            )
            self._jobs[job.job_id] = job
            self._character_queue.append(job.job_id)
            self._character_job_kwargs[job.job_id] = {
                "character_ids": character_ids,
                "prompt_level": prompt_level,
            }
        self._dispatch_character_job()
        return job

    def _dispatch_character_job(self) -> None:
        to_start: tuple[str, dict] | None = None
        with self._lock:
            if self._active_character_job is None:
                while self._character_queue:
                    job_id = self._character_queue.popleft()
                    job = self._jobs.get(job_id)
                    if not job or job.status != "queued":
                        continue
                    kwargs = self._character_job_kwargs.pop(job_id, {})
                    self._active_character_job = job_id
                    to_start = (job_id, kwargs)
                    break

        if to_start:
            job_id, kwargs = to_start
            thread = threading.Thread(
                target=self._run_character_generation,
                args=(job_id, kwargs.get("character_ids", []), kwargs.get("prompt_level", 1)),
                daemon=True,
                name=f"char-generation-{job_id[:8]}",
            )
            thread.start()

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def _increment_job(self, job_id: str, **deltas: int) -> None:
        """후처리 콜백(별도 스레드)에서 완료/실패/자동검사 카운터를 안전하게 증가시킨다."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, delta in deltas.items():
                setattr(job, key, getattr(job, key) + delta)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _make_postprocess_callback(self, job_id: str, character_tag: str, index: int, total: int):
        """후처리(파일저장·자동검사) future 완료 시 진행률/카운터를 갱신하는 콜백을 만든다.

        콜백은 후처리 워커 스레드에서 실행되므로 공유 상태는 반드시 락을 타는
        _increment_job/_update_job을 통해서만 건드린다.
        """

        def _callback(future: Future) -> None:
            try:
                image = future.result()
            except Exception as exc:
                self._increment_job(job_id, failed=1)
                self._update_job(job_id, message=f"{character_tag} 실패: {exc}")
                return
            status_field = {
                "pass": "auto_pass",
                "warning": "auto_warning",
                "reject_candidate": "auto_reject",
            }.get(image.auto_status)
            deltas: dict[str, int] = {"completed": 1}
            if status_field:
                deltas[status_field] = 1
            self._increment_job(job_id, **deltas)
            self._update_job(
                job_id,
                current=index,
                last_image_path=image.image_path,
                message=f"{character_tag} 저장 · 자동검사 {image.auto_status} ({index}/{total})",
            )

        return _callback

    def _run_generation(
        self,
        job_id: str,
        series_id: int,
        character_ids: list[int] | None,
        prompt_level: int,
        require_confirmed: bool,
    ) -> None:
        db = SessionLocal()
        series: Series | None = None
        status_before_generation = ""
        marks_series_generated = False
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
            marks_series_generated = queue_covers_all_eligible_characters(character_ids, queue_payload)
            status_before_generation = mark_series_generating(db, series)
            self._update_job(
                job_id,
                status_before_generation=status_before_generation,
                marks_series_generated=marks_series_generated,
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
                restore_series_status(db, series, status_before_generation)
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

            pending_futures: list[tuple[int, Future]] = []
            for index, generation_job in enumerate(jobs, start=1):
                if self._is_cancelled(job_id):
                    restore_series_status(db, series, status_before_generation)
                    return

                # 체크포인트: 이미지 생성 전 일시정지 확인
                if not self._check_pause(job_id):
                    restore_series_status(db, series, status_before_generation)
                    return

                if index > 1:
                    wait_between_naia_generations()

                character = db.query(Character).filter(Character.id == generation_job.character_id).first()
                if not character:
                    self._increment_job(job_id, failed=1)
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
                    # 저장·자동검사(HF 태거 호출 포함)는 별도 스레드로 넘기고, 메인 루프는
                    # 곧바로 다음 NAIA 요청으로 넘어간다 (후처리와 다음 생성이 겹쳐 실행됨).
                    future = self._postprocess_executor.submit(
                        _postprocess_character_image, character.id, generation_job.id, image_bytes
                    )
                    future.add_done_callback(
                        self._make_postprocess_callback(job_id, character.character_tag, index, len(jobs))
                    )
                    pending_futures.append((generation_job.character_id, future))
                except Exception as exc:
                    self._increment_job(job_id, failed=1)
                    service.mark_job_failed(generation_job, str(exc))
                    self._update_job(
                        job_id,
                        current=index,
                        message=f"{character.character_tag} 실패: {exc}",
                    )

            # 에스컬레이션/커버 선택은 이번 배치의 자동검사 결과가 필요하므로, 아직 끝나지
            # 않은 후처리(태깅 등)가 있다면 여기서 완료를 기다린다.
            char_batch_images: dict[int, list] = defaultdict(list)
            for char_id, future in pending_futures:
                try:
                    char_batch_images[char_id].append(future.result())
                except Exception:
                    pass  # 실패 카운트는 완료 콜백에서 이미 반영됨

            # 이후 에스컬레이션/최종 요약에서 이어서 누적할 수 있도록 후처리 콜백이
            # 반영한 카운터를 로컬 변수로 동기화한다.
            job_snapshot = self.get_job(job_id)
            completed = job_snapshot.completed if job_snapshot else 0
            failed = job_snapshot.failed if job_snapshot else 0
            auto_pass = job_snapshot.auto_pass if job_snapshot else 0
            auto_warning = job_snapshot.auto_warning if job_snapshot else 0
            auto_reject = job_snapshot.auto_reject if job_snapshot else 0

            # ── 자동 레벨 에스컬레이션 ──────────────────────────────────────
            escalation_chars = [
                char_id
                for char_id, imgs in char_batch_images.items()
                if imgs and all(img.auto_status == "reject_candidate" for img in imgs)
            ]
            if escalation_chars and not self._is_cancelled(job_id):
                self._update_job(
                    job_id,
                    phase="escalating",
                    message=f"자동 레벨 상승 · {len(escalation_chars)}명 재시도 중...",
                )
                for char_id in escalation_chars:
                    if self._is_cancelled(job_id):
                        break
                    # 에스컬레이션 전 일시정지 확인
                    if not self._check_pause(job_id):
                        restore_series_status(db, series, status_before_generation)
                        return
                    character = db.query(Character).filter(Character.id == char_id).first()
                    if not character:
                        continue
                    current_level = prompt_level
                    char_imgs = list(char_batch_images[char_id])
                    for attempt in range(_MAX_ESCALATIONS):
                        if any(img.auto_status != "reject_candidate" for img in char_imgs):
                            break
                        if current_level >= _MAX_PROMPT_LEVEL:
                            break
                        current_level += 1
                        esc_job = None
                        try:
                            config = service.get_prompt_config()
                            esc_prompt, esc_negative = build_full_prompt(
                                character,
                                prompt_level=current_level,
                                prompt_config=config,
                            )
                            esc_job = GenerationJob(
                                character_id=character.id,
                                prompt_level=current_level,
                                prompt=esc_prompt,
                                negative_prompt=esc_negative,
                                count=1,
                                status="pending",
                            )
                            db.add(esc_job)
                            db.flush()
                            db.refresh(esc_job)
                            self._update_job(
                                job_id,
                                message=(
                                    f"{character.character_tag} "
                                    f"Level {current_level} 재생성 "
                                    f"({attempt + 1}/{_MAX_ESCALATIONS})"
                                ),
                            )
                            wait_between_naia_generations()
                            image_bytes, _ = generate_and_fetch_image(
                                client,
                                prompt=esc_prompt,
                                negative_prompt=esc_negative,
                                known_history_ids=known_history_ids,
                            )
                            new_img = service.import_generated_image(
                                character=character,
                                generation_job=esc_job,
                                image_bytes=image_bytes,
                            )
                            char_imgs.append(new_img)
                            char_batch_images[char_id].append(new_img)
                            completed += 1
                            if new_img.auto_status == "pass":
                                auto_pass += 1
                            elif new_img.auto_status == "warning":
                                auto_warning += 1
                            else:
                                auto_reject += 1
                            self._update_job(
                                job_id,
                                completed=completed,
                                auto_pass=auto_pass,
                                auto_warning=auto_warning,
                                auto_reject=auto_reject,
                                last_image_path=new_img.image_path,
                                message=(
                                    f"{character.character_tag} "
                                    f"Level {current_level} → {new_img.auto_status}"
                                ),
                            )
                        except Exception as exc:
                            failed += 1
                            if esc_job is not None:
                                service.mark_job_failed(esc_job, str(exc))
                            self._update_job(
                                job_id,
                                failed=failed,
                                message=f"{character.character_tag} 에스컬레이션 실패: {exc}",
                            )
                            break

            # ── 커버 이미지 자동 선택 ──────────────────────────────────────
            if not self._is_cancelled(job_id):
                self._update_job(job_id, message="커버 이미지 자동 선택 중...")
                for char_id, char_imgs in char_batch_images.items():
                    if char_imgs:
                        service.auto_select_cover(char_id, char_imgs)

            summary = f"완료: {completed}장 저장 · 실패 {failed}"
            if completed:
                summary += f" · 자동검사 pass {auto_pass} / warning {auto_warning} / reject {auto_reject}"
            batch_success = failed == 0 and completed == len(jobs) and len(jobs) > 0
            final_status = "completed" if batch_success else ("failed" if completed == 0 else "completed")
            finalize_series_after_batch(
                db,
                series,
                previous_status=status_before_generation,
                batch_success=batch_success,
                marks_series_generated=marks_series_generated,
            )
            self._update_job(
                job_id,
                status=final_status,
                phase="completed" if batch_success else ("failed" if completed == 0 else "completed"),
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
            if series is not None and status_before_generation:
                restore_series_status(db, series, status_before_generation)
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

    def _run_character_generation(
        self,
        job_id: str,
        character_ids: list[int],
        prompt_level: int,
    ) -> None:
        """캐릭터 목록(GlobalCharacter) 중심 생성. series 상태 변경(mark_series_generating 등)이
        전혀 없다는 점을 제외하면 _run_generation과 동일한 구조."""
        db = SessionLocal()
        try:
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
                job_id, status="running", phase="preparing", message="캐릭터 목록 생성 큐 준비 중"
            )

            try:
                queue_payload = service.prepare_queue_global(character_ids, prompt_level=prompt_level)
            except ValueError as exc:
                self._update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message=str(exc),
                    error=str(exc),
                    finished_at=_utc_now(),
                )
                return

            images_per_character = service.get_images_per_character()
            jobs = service.create_generation_jobs_global(
                queue_payload, images_per_character=images_per_character
            )
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
                message="캐릭터 목록 이미지 생성 시작",
                total=len(jobs),
                current=0,
            )

            pending_futures: list[tuple[int, Future]] = []
            for index, generation_job in enumerate(jobs, start=1):
                if self._is_cancelled(job_id):
                    break
                if not self._check_pause(job_id):
                    break

                if index > 1:
                    wait_between_naia_generations()

                character = (
                    db.query(GlobalCharacter)
                    .filter(GlobalCharacter.id == generation_job.global_character_id)
                    .first()
                )
                if not character:
                    self._increment_job(job_id, failed=1)
                    service.mark_job_failed_global(generation_job, "Character not found")
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
                    # 저장·자동검사(HF 태거 호출 포함)는 별도 스레드로 넘기고, 메인 루프는
                    # 곧바로 다음 NAIA 요청으로 넘어간다.
                    future = self._postprocess_executor.submit(
                        _postprocess_global_character_image, character.id, generation_job.id, image_bytes
                    )
                    future.add_done_callback(
                        self._make_postprocess_callback(job_id, character.character_tag, index, len(jobs))
                    )
                    pending_futures.append((generation_job.global_character_id, future))
                except Exception as exc:
                    self._increment_job(job_id, failed=1)
                    service.mark_job_failed_global(generation_job, str(exc))
                    self._update_job(
                        job_id,
                        current=index,
                        message=f"{character.character_tag} 실패: {exc}",
                    )

            # 커버 자동 선택에 필요한 자동검사 결과를 위해 남은 후처리 완료를 기다린다.
            char_batch_images: dict[int, list] = defaultdict(list)
            for char_id, future in pending_futures:
                try:
                    char_batch_images[char_id].append(future.result())
                except Exception:
                    pass  # 실패 카운트는 완료 콜백에서 이미 반영됨

            job_snapshot = self.get_job(job_id)
            completed = job_snapshot.completed if job_snapshot else 0
            failed = job_snapshot.failed if job_snapshot else 0
            auto_pass = job_snapshot.auto_pass if job_snapshot else 0
            auto_warning = job_snapshot.auto_warning if job_snapshot else 0
            auto_reject = job_snapshot.auto_reject if job_snapshot else 0

            if not self._is_cancelled(job_id):
                self._update_job(job_id, message="커버 이미지 자동 선택 중...")
                for char_id, char_imgs in char_batch_images.items():
                    if char_imgs:
                        service.auto_select_cover_global(char_id, char_imgs)

            summary = f"완료: {completed}장 저장 · 실패 {failed}"
            if completed:
                summary += f" · 자동검사 pass {auto_pass} / warning {auto_warning} / reject {auto_reject}"
            if self._is_cancelled(job_id):
                final_status = "cancelled"
            elif completed == 0 and failed > 0:
                final_status = "failed"
            else:
                final_status = "completed"
            self._update_job(
                job_id,
                status=final_status,
                phase=final_status,
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
                message="캐릭터 목록 이미지 생성 중 오류 발생",
                error=str(exc),
                finished_at=_utc_now(),
            )
        finally:
            db.close()
            with self._lock:
                if self._active_character_job == job_id:
                    self._active_character_job = None
            self._dispatch_character_job()


generation_job_manager = GenerationJobManager()
