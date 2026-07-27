from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.integrations.image_tagger.hf_wd_tagger import (
    TAGGER_AUTH_ERROR,
    TAGGER_ERROR,
    TAGGER_INVALID_RESPONSE,
    TAGGER_MODEL_NOT_FOUND,
    TAGGER_MODEL_UNAVAILABLE,
    TAGGER_RATE_LIMITED,
    TAGGER_SERVICE_UNAVAILABLE,
    TAGGER_TIMEOUT,
    TAGGER_TOKEN_PERMISSION,
)
from app.integrations.image_tagger.local_wd_tagger import (
    DEFAULT_LOCAL_WD_MODEL,
    is_local_wd_model_installed,
    local_wd_model_paths,
)
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.services.db_write_queue import commit_db_session, job_write_context
from app.services.identity_checker import IDENTITY_CHECKER_VERSION, check_identity
from app.services.prompt_service import v2_multicolor_prompt_candidates

MIN_RECHECK_BATCH_SIZE = 100
MAX_RECHECK_BATCH_SIZE = 500
DEFAULT_RECHECK_BATCH_SIZE = 200
# Local-only identity path: only a missing local model is a job-stopping fault.
FATAL_TAGGER_REASONS = {
    TAGGER_MODEL_UNAVAILABLE,
}
TAGGER_FAILURE_REASONS = (
    TAGGER_ERROR,
    "tagger_unavailable",
    TAGGER_AUTH_ERROR,
    TAGGER_TOKEN_PERMISSION,
    TAGGER_MODEL_NOT_FOUND,
    TAGGER_MODEL_UNAVAILABLE,
    TAGGER_RATE_LIMITED,
    TAGGER_TIMEOUT,
    TAGGER_INVALID_RESPONSE,
    TAGGER_SERVICE_UNAVAILABLE,
    "tagger_no_predictions",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PendingImageRecheckPreview:
    eligible_images: int
    excluded_completed: int
    missing_files: int
    batch_size: int
    tagger_failures_only: bool = True
    first_image_id: int | None = None
    last_image_id: int | None = None


@dataclass
class PendingImageRecheckJobState:
    job_id: str
    status: str = "queued"
    phase: str = "queued"
    message: str = "Pending image identity recheck queued."
    current: int = 0
    total: int = 0
    completed: int = 0
    succeeded: int = 0
    warnings: int = 0
    rejected: int = 0
    failed: int = 0
    skipped: int = 0
    batch_size: int = DEFAULT_RECHECK_BATCH_SIZE
    tagger_failures_only: bool = True
    last_image_id: int | None = None
    current_image_id: int | None = None
    current_character_id: int | None = None
    current_character_tag: str = ""
    identity_status: str | None = None
    identity_reasons: list[str] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None


class PendingImageRecheckJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, PendingImageRecheckJobState] = {}
        self._active_job_id: str | None = None
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _clamp_batch_size(batch_size: int) -> int:
        return max(MIN_RECHECK_BATCH_SIZE, min(MAX_RECHECK_BATCH_SIZE, batch_size))

    @staticmethod
    def _base_pending_query(db: Session):
        return (
            db.query(GlobalCharacterImage)
            .join(GlobalCharacter, GlobalCharacter.id == GlobalCharacterImage.global_character_id)
            .outerjoin(
                GlobalCharacterReview,
                GlobalCharacterReview.global_character_id == GlobalCharacter.id,
            )
            .filter(GlobalCharacterImage.is_rejected.is_(False))
        )

    @classmethod
    def _tagger_failure_filter(cls):
        return or_(
            *[
                GlobalCharacterImage.identity_reasons.like(f'%"{reason}"%')
                for reason in TAGGER_FAILURE_REASONS
            ]
        )

    @classmethod
    def _eligible_query(
        cls,
        db: Session,
        *,
        after_image_id: int | None = None,
        tagger_failures_only: bool = True,
    ):
        query = (
            cls._base_pending_query(db)
            .filter(
                or_(
                    GlobalCharacterReview.id.is_(None),
                    GlobalCharacterReview.review_status != "completed",
                )
            )
        )
        if tagger_failures_only:
            query = query.filter(cls._tagger_failure_filter())
        if after_image_id is not None:
            query = query.filter(GlobalCharacterImage.id > after_image_id)
        return query.order_by(GlobalCharacterImage.id.asc())

    @classmethod
    def _excluded_completed_count(cls, db: Session) -> int:
        return (
            cls._base_pending_query(db)
            .filter(GlobalCharacterReview.review_status == "completed")
            .count()
        )

    def _missing_files_count(
        self, db: Session, *, tagger_failures_only: bool = True
    ) -> int:
        missing = 0
        cursor: int | None = None
        while True:
            rows = (
                self._eligible_query(
                    db,
                    after_image_id=cursor,
                    tagger_failures_only=tagger_failures_only,
                )
                .with_entities(GlobalCharacterImage.id, GlobalCharacterImage.image_path)
                .limit(MAX_RECHECK_BATCH_SIZE)
                .all()
            )
            if not rows:
                return missing
            for image_id, image_path in rows:
                cursor = image_id
                if not self._resolve_image_path(image_path).is_file():
                    missing += 1

    def preview(
        self,
        db: Session,
        *,
        batch_size: int = DEFAULT_RECHECK_BATCH_SIZE,
        tagger_failures_only: bool = True,
    ) -> PendingImageRecheckPreview:
        clamped = self._clamp_batch_size(batch_size)
        query = self._eligible_query(db, tagger_failures_only=tagger_failures_only)
        total = query.count()
        first = query.first()
        last = (
            self._eligible_query(db, tagger_failures_only=tagger_failures_only)
            .with_entities(GlobalCharacterImage.id)
            .order_by(None)
            .order_by(GlobalCharacterImage.id.desc())
            .first()
        )
        return PendingImageRecheckPreview(
            eligible_images=total,
            excluded_completed=self._excluded_completed_count(db),
            missing_files=self._missing_files_count(
                db, tagger_failures_only=tagger_failures_only
            ),
            batch_size=clamped,
            tagger_failures_only=tagger_failures_only,
            first_image_id=first.id if first else None,
            last_image_id=last[0] if last else None,
        )

    def start(
        self,
        *,
        batch_size: int = DEFAULT_RECHECK_BATCH_SIZE,
        tagger_failures_only: bool = True,
    ) -> PendingImageRecheckJobState | None:
        job = PendingImageRecheckJobState(
            job_id=str(uuid.uuid4()),
            batch_size=self._clamp_batch_size(batch_size),
            tagger_failures_only=tagger_failures_only,
        )
        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs.get(self._active_job_id)
                if active and active.status in {"queued", "running"}:
                    return None
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id
        thread = threading.Thread(
            target=self._run,
            args=(job.job_id,),
            daemon=True,
            name=f"pending-image-recheck-{job.job_id[:8]}",
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> PendingImageRecheckJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_current_or_latest(self) -> PendingImageRecheckJobState | None:
        with self._lock:
            if self._active_job_id is not None:
                return self._jobs.get(self._active_job_id)
            if not self._jobs:
                return None
            return sorted(self._jobs.values(), key=lambda item: item.started_at, reverse=True)[0]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return False
            self._cancelled.add(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.message = "Cancellation requested."
            job.finished_at = _utc_now()
        return True

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

    @staticmethod
    def _resolve_image_path(image_path: str) -> Path:
        path = Path(image_path)
        if path.is_absolute():
            return path
        return settings.project_root / path

    def _run(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            with job_write_context(job_id):
                job = self.get_job(job_id)
                batch_size = job.batch_size if job else DEFAULT_RECHECK_BATCH_SIZE
                tagger_failures_only = (
                    job.tagger_failures_only if job is not None else True
                )
                # Preview also checks every candidate path so it can report
                # missing files. Avoid duplicating that potentially 100k+
                # filesystem scan before the actual recheck.
                total = self._eligible_query(
                    db, tagger_failures_only=tagger_failures_only
                ).count()
                scope = (
                    "tagger-failure pending-review images"
                    if tagger_failures_only
                    else "pending-review images"
                )
                self._update(
                    job_id,
                    status="running",
                    phase="rechecking",
                    total=total,
                    message=f"Rechecking identity for {total} {scope}.",
                )
                if not is_local_wd_model_installed(DEFAULT_LOCAL_WD_MODEL):
                    paths = local_wd_model_paths(DEFAULT_LOCAL_WD_MODEL)
                    message = (
                        "Local WD tagger model is not installed. Download "
                        f"{DEFAULT_LOCAL_WD_MODEL} before starting pending image recheck."
                    )
                    self._append_error(
                        job_id,
                        {
                            "error": TAGGER_MODEL_UNAVAILABLE,
                            "detail": message,
                            "cache_dir": str(paths.cache_dir),
                        },
                    )
                    self._update(
                        job_id,
                        status="failed",
                        phase="failed",
                        message=message,
                        identity_status="warning",
                        identity_reasons=[TAGGER_MODEL_UNAVAILABLE],
                        finished_at=_utc_now(),
                    )
                    return
                cursor: int | None = None

                while not self._is_cancelled(job_id):
                    batch = (
                        self._eligible_query(
                            db,
                            after_image_id=cursor,
                            tagger_failures_only=tagger_failures_only,
                        )
                        .limit(batch_size)
                        .all()
                    )
                    if not batch:
                        break
                    for image in batch:
                        if self._is_cancelled(job_id):
                            break
                        cursor = image.id
                        character = image.global_character or db.get(GlobalCharacter, image.global_character_id)
                        self._update(
                            job_id,
                            current_image_id=image.id,
                            current_character_id=character.id if character else None,
                            current_character_tag=character.character_tag if character else "",
                            last_image_id=image.id,
                            message=f"Rechecking image {image.id}",
                        )
                        try:
                            if character is None:
                                raise RuntimeError("Character not found")
                            resolved = self._resolve_image_path(image.image_path)
                            if not resolved.is_file():
                                self._increment(job_id, skipped=1, current=1)
                                self._append_error(
                                    job_id,
                                    {
                                        "image_id": image.id,
                                        "character_id": image.global_character_id,
                                        "error": "image_file_missing",
                                    },
                                )
                                continue

                            identity = check_identity(
                                resolved,
                                character_tag=character.character_tag,
                                primary_hair_color=character.primary_hair_color,
                                expected_multicolor_tags=tuple(
                                    v2_multicolor_prompt_candidates(db, character.id)
                                ),
                                gender=character.gender,
                            )
                            fatal_reason = next(
                                (
                                    reason
                                    for reason in identity.reasons
                                    if reason in FATAL_TAGGER_REASONS
                                ),
                                None,
                            )
                            if fatal_reason:
                                self._append_error(
                                    job_id,
                                    {
                                        "image_id": image.id,
                                        "character_id": image.global_character_id,
                                        "error": fatal_reason,
                                    },
                                )
                                self._update(
                                    job_id,
                                    status="failed",
                                    phase="failed",
                                    message=(
                                        "Pending image identity recheck stopped because "
                                        f"local WD tagger is unavailable: {fatal_reason}."
                                    ),
                                    identity_status=identity.status,
                                    identity_reasons=list(identity.reasons),
                                    finished_at=_utc_now(),
                                )
                                return
                            now = datetime.now()
                            savepoint = db.begin_nested()
                            try:
                                image.identity_status = identity.status
                                image.character_confidence = identity.character_confidence
                                image.hair_color_confidence = identity.hair_color_confidence
                                image.conflicting_character_tag = identity.conflicting_character_tag
                                image.conflicting_character_confidence = identity.conflicting_character_confidence
                                image.identity_reasons = json.dumps(identity.reasons, ensure_ascii=False)
                                image.suggested_multicolor_tags = json.dumps(
                                    identity.suggested_multicolor_tags, ensure_ascii=False
                                )
                                image.identity_checked_at = now
                                image.identity_checker_version = IDENTITY_CHECKER_VERSION
                                savepoint.commit()
                            except Exception:
                                savepoint.rollback()
                                raise
                            self._increment(job_id, completed=1, current=1)
                            if identity.status == "pass":
                                self._increment(job_id, succeeded=1)
                            elif identity.status == "warning":
                                self._increment(job_id, warnings=1)
                            elif identity.status == "reject":
                                self._increment(job_id, rejected=1)
                            self._update(
                                job_id,
                                identity_status=identity.status,
                                identity_reasons=list(identity.reasons),
                            )
                        except Exception as exc:
                            self._increment(job_id, failed=1, current=1)
                            self._append_error(
                                job_id,
                                {
                                    "image_id": image.id,
                                    "character_id": image.global_character_id,
                                    "error": str(exc),
                                },
                            )

                    commit_db_session(db)

                snapshot = self.get_job(job_id)
                if self._is_cancelled(job_id):
                    final_status = "cancelled"
                else:
                    final_status = "completed"
                self._update(
                    job_id,
                    status=final_status,
                    phase=final_status,
                    message=(
                        f"Completed {snapshot.completed if snapshot else 0}, "
                        f"skipped {snapshot.skipped if snapshot else 0}, "
                        f"failed {snapshot.failed if snapshot else 0}."
                    ),
                    finished_at=_utc_now(),
                )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                phase="failed",
                message="Pending image identity recheck failed.",
                errors=[{"error": str(exc)}],
                finished_at=_utc_now(),
            )
        finally:
            db.close()
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None


pending_image_recheck_job_manager = PendingImageRecheckJobManager()
