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
    phase: str | None = None
    collect_total: int = 0
    collect_done: int = 0
    collect_failed: int = 0
    extract_total: int = 0
    extract_done: int = 0
    extract_failed: int = 0
    generate_total: int = 0
    generate_done: int = 0
    generate_failed: int = 0
    auto_generate: bool = False
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
                generate_total=s.generate_total,
                generate_done=s.generate_done,
                generate_failed=s.generate_failed,
                auto_generate=s.auto_generate,
                current_series_tag=s.current_series_tag,
                current_job_message=s.current_job_message,
                started_at=s.started_at,
                finished_at=s.finished_at,
                errors=list(s.errors),
            )

    def start(self, *, auto_generate: bool = False) -> bool:
        with self._lock:
            if self._state.status in {"running", "stopping"}:
                return False
            self._state = PipelineState(
                status="running",
                started_at=_utc_now(),
                auto_generate=auto_generate,
            )
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

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()

    def _run(self) -> None:
        try:
            self._run_concurrent_phases()
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

    # ── 대상 시리즈 조회 ──────────────────────────────────────────────────────

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
        """파이프라인 시작 시 이미 collected 상태인 시리즈 (바로 추출 시작)."""
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

    def _get_generate_targets(self) -> list[tuple[int, str]]:
        """파이프라인 시작 시 이미 tagged 상태인 시리즈 (auto_generate 시 즉시 생성 시작)."""
        db = SessionLocal()
        try:
            rows = (
                db.query(Series.id, Series.series_tag)
                .filter(
                    Series.parent_series_id.is_(None),
                    Series.status == "tagged",
                )
                .order_by(Series.priority.asc(), Series.post_count.desc(), Series.id.asc())
                .all()
            )
            return [(row.id, row.series_tag) for row in rows]
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

    def _suggest_level(self, series_id: int) -> int:
        """시리즈 내 캐릭터들의 추천 생성 레벨 (1~3)."""
        db = SessionLocal()
        try:
            from app.services.generation_service import GenerationService
            result = GenerationService(db).suggest_batch_level(series_id=series_id)
            return int(result.get("suggested_level", 1))
        except Exception:
            return 1
        finally:
            db.close()

    # ── 핵심: 시리즈 단위 동시 파이프라인 ──────────────────────────────────────

    def _run_concurrent_phases(self) -> None:
        """수집 → 추출 → (선택) 생성을 시리즈 단위로 동시 진행.

        Phase 1 (수집)이 완전히 끝나길 기다리지 않고, 한 시리즈의 수집이
        끝나면 즉시 그 시리즈의 추출을 시작한다.
        """
        from app.services.generation_job_manager import generation_job_manager

        # ── 1단계: 대상 계산 ───────────────────────────────────────────────
        collect_targets = self._get_collect_targets()
        extract_targets = self._get_extract_targets()
        generate_targets = self._get_generate_targets() if self._state.auto_generate else []

        with self._lock:
            self._state.collect_total = len(collect_targets)
            self._state.extract_total = len(extract_targets)
            self._state.generate_total = len(generate_targets)
            self._state.phase = (
                "collecting" if collect_targets
                else "extracting" if extract_targets
                else "generating" if generate_targets
                else None
            )

        # ── 2단계: 작업 제출 ───────────────────────────────────────────────
        # job_id → (series_id, series_tag)
        collect_job_map: dict[str, tuple[int, str]] = {}
        extract_job_map: dict[str, tuple[int, str]] = {}
        generate_job_map: dict[str, tuple[int, str]] = {}

        for series_id, series_tag in collect_targets:
            if self._should_stop():
                break
            if not self._is_still_pending(series_id):
                with self._lock:
                    self._state.collect_total = max(0, self._state.collect_total - 1)
                continue
            try:
                job = series_job_manager.start_series_collect(series_id, series_tag)
                collect_job_map[job.job_id] = (series_id, series_tag)
            except Exception as exc:
                with self._lock:
                    self._state.collect_failed += 1
                    self._state.errors.append(f"[수집 제출] {series_tag}: {exc}")

        for series_id, series_tag in extract_targets:
            if self._should_stop():
                break
            try:
                job = series_job_manager.start_appearance_extract(series_id, series_tag)
                extract_job_map[job.job_id] = (series_id, series_tag)
            except Exception as exc:
                with self._lock:
                    self._state.extract_failed += 1
                    self._state.errors.append(f"[추출 제출] {series_tag}: {exc}")

        # tagged 상태 시리즈 → auto_generate면 즉시 생성 제출
        for series_id, series_tag in generate_targets:
            if self._should_stop():
                break
            try:
                prompt_level = self._suggest_level(series_id)
                gen_job = generation_job_manager.start_generation(
                    series_id,
                    character_ids=None,
                    prompt_level=prompt_level,
                    require_confirmed=False,
                )
                generate_job_map[gen_job.job_id] = (series_id, series_tag)
            except Exception as exc:
                with self._lock:
                    self._state.generate_failed += 1
                    self._state.errors.append(f"[생성 제출] {series_tag}: {exc}")

        # ── 3단계: 폴링 루프 ───────────────────────────────────────────────
        collect_remaining: set[str] = set(collect_job_map)
        extract_remaining: set[str] = set(extract_job_map)
        generate_remaining: set[str] = set(generate_job_map)

        tick = 0
        while collect_remaining or extract_remaining or generate_remaining:
            if self._should_stop():
                self._drain_on_stop(collect_remaining, extract_remaining)
                return

            time.sleep(1)
            tick += 1

            # 매 틱: 현재 실행 중 작업 표시 갱신
            running_jobs = series_job_manager.get_running_jobs()
            relevant = [j for j in running_jobs if j.job_id in collect_remaining] or \
                       [j for j in running_jobs if j.job_id in extract_remaining]
            if relevant:
                with self._lock:
                    self._state.current_series_tag = relevant[0].series_tag
                    self._state.current_job_message = relevant[0].message

            if tick % 5 != 0:
                continue

            # ── 수집 완료 처리 → 즉시 추출 제출 ──────────────────────────
            finished_collect: set[str] = set()
            for job_id in list(collect_remaining):
                job = series_job_manager.get_job(job_id)
                if not job or job.status not in {"completed", "failed", "cancelled"}:
                    continue
                finished_collect.add(job_id)
                series_id, series_tag = collect_job_map[job_id]

                if job.status == "completed":
                    with self._lock:
                        self._state.collect_done += 1
                    # 수집 완료 직후 추출 즉시 시작
                    try:
                        ext_job = series_job_manager.start_appearance_extract(series_id, series_tag)
                        extract_job_map[ext_job.job_id] = (series_id, series_tag)
                        extract_remaining.add(ext_job.job_id)
                        with self._lock:
                            self._state.extract_total += 1
                    except Exception as exc:
                        with self._lock:
                            self._state.extract_failed += 1
                            self._state.errors.append(f"[추출 제출] {series_tag}: {exc}")
                else:
                    with self._lock:
                        self._state.collect_failed += 1
                        if job.error:
                            self._state.errors.append(f"[수집] {series_tag}: {job.error}")

            collect_remaining -= finished_collect

            # ── 추출 완료 처리 → (선택) 생성 제출 ────────────────────────
            finished_extract: set[str] = set()
            for job_id in list(extract_remaining):
                job = series_job_manager.get_job(job_id)
                if not job or job.status not in {"completed", "failed", "cancelled"}:
                    continue
                finished_extract.add(job_id)
                series_id, series_tag = extract_job_map[job_id]

                if job.status == "completed":
                    with self._lock:
                        self._state.extract_done += 1

                    if self._state.auto_generate and not self._should_stop():
                        try:
                            prompt_level = self._suggest_level(series_id)
                            gen_job = generation_job_manager.start_generation(
                                series_id,
                                character_ids=None,
                                prompt_level=prompt_level,
                                require_confirmed=False,
                            )
                            generate_job_map[gen_job.job_id] = (series_id, series_tag)
                            generate_remaining.add(gen_job.job_id)
                            with self._lock:
                                self._state.generate_total += 1
                        except Exception as exc:
                            with self._lock:
                                self._state.generate_failed += 1
                                self._state.errors.append(f"[생성 제출] {series_tag}: {exc}")
                else:
                    with self._lock:
                        self._state.extract_failed += 1
                        if job.error:
                            self._state.errors.append(f"[추출] {series_tag}: {job.error}")

            extract_remaining -= finished_extract

            # ── 생성 완료 처리 ────────────────────────────────────────────
            finished_generate: set[str] = set()
            for job_id in list(generate_remaining):
                gen_job = generation_job_manager.get_job(job_id)
                if not gen_job or gen_job.status not in {"completed", "failed", "cancelled"}:
                    continue
                finished_generate.add(job_id)
                series_id, series_tag = generate_job_map[job_id]
                if gen_job.status == "completed":
                    with self._lock:
                        self._state.generate_done += 1
                else:
                    with self._lock:
                        self._state.generate_failed += 1
                        if gen_job.error:
                            self._state.errors.append(f"[생성] {series_tag}: {gen_job.error}")

            generate_remaining -= finished_generate

            # ── 현재 Phase 표시 업데이트 ──────────────────────────────────
            with self._lock:
                has_c = bool(collect_remaining)
                has_e = bool(extract_remaining)
                has_g = bool(generate_remaining)
                if has_c and has_e:
                    self._state.phase = "collecting+extracting"
                elif has_c:
                    self._state.phase = "collecting"
                elif has_e and has_g:
                    self._state.phase = "extracting+generating"
                elif has_e:
                    self._state.phase = "extracting"
                elif has_g:
                    self._state.phase = "generating"

    def _drain_on_stop(
        self,
        collect_remaining: set[str],
        extract_remaining: set[str],
    ) -> None:
        """중지 요청 시 대기 중(queued) 작업 취소, 실행 중 작업은 자연 완료 대기."""
        all_remaining = collect_remaining | extract_remaining
        for job_id in list(all_remaining):
            job = series_job_manager.get_job(job_id)
            if job and job.status == "queued":
                series_job_manager.cancel_job(job_id)
                all_remaining.discard(job_id)
                collect_remaining.discard(job_id)
                extract_remaining.discard(job_id)

        # 실행 중인 작업이 끝날 때까지 대기
        while collect_remaining or extract_remaining:
            time.sleep(1)
            for job_id in list(collect_remaining | extract_remaining):
                job = series_job_manager.get_job(job_id)
                if not job or job.status not in {"queued", "running"}:
                    collect_remaining.discard(job_id)
                    extract_remaining.discard(job_id)


pipeline_manager = PipelineManager()
