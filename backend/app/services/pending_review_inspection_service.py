from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.services.character_image_service import run_v2_quality_identity_checks
from app.services.db_write_queue import commit_db_session
from app.services.identity_checker import IDENTITY_CHECKER_VERSION, IdentityCheckResult, is_tagger_failure
from app.services.inspection_repair import (
    STAGE_AUTO_ZERO,
    STAGE_DONE,
    STAGE_IDENTITY_EYE,
    STAGE_IDENTITY_HAIR,
    STAGE_IDENTITY_MULTICOLOR,
    STAGE_QUALITY,
    STAGE_SEMANTIC_GALLERY,
    STAGE_SEMANTIC_OUTFIT,
    RepairContext,
    decide_repair_stage,
    identity_insufficient,
    needs_identity_repair,
)
from app.services.quality_checker import QUALITY_CHECKER_VERSION
from app.services.reference_profile_service import REFERENCE_PROFILE_VERSION
from app.services.settings_service import SettingsService
from app.services.v2_generation_job_manager import v2_generation_job_manager
from app.services.v2_generation_pipeline import V2GenerationPipeline, V2PipelineResult

PENDING_INSPECTION_VERSION = "v1.3"
AUTO_RATING_CONFIDENCE = 0.85
PREFILL_RATING_CONFIDENCE = 0.72
DEFAULT_AUDIT_SAMPLE_RATE = 0.10
DEFAULT_MAX_REGENERATIONS = 2
# Identity ladder (hair/multicolor/eye) plus up to two semantic passes needs headroom
# beyond the historical per-character regeneration default of 2.
MAX_STAGE_REGENERATIONS = 6
MAX_TRACKED_TEST_CHARACTERS = 2000
MAX_RESET_CHARACTERS = 1000


@dataclass
class PendingInspectionSummary:
    requested_limit: int
    inspected: int = 0
    profile_built: int = 0
    passed: int = 0
    warnings: int = 0
    rejected: int = 0
    characters_regenerated: int = 0
    regeneration_images: int = 0
    rejected_files_removed: int = 0
    auto_completed: int = 0
    audit_kept_pending: int = 0
    prefilled_pending: int = 0
    suggested_only: int = 0
    ratings: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Only characters that actually completed _inspect_existing in this batch.
    inspected_character_ids: list[int] = field(default_factory=list)
    # Page-test / operator diagnostics (cheap counters, no per-image payloads).
    tagger_success: int = 0
    tagger_error: int = 0
    semantic_pass: int = 0
    semantic_warning: int = 0
    semantic_reject: int = 0
    reference_loaded: int = 0
    reference_failed: int = 0
    regeneration_requested: int = 0
    skipped_current_version: int = 0
    # Per-character repair diagnostics for page tests / operator triage.
    character_diagnostics: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PendingInspectionResetSummary:
    requested: int
    matched: int = 0
    images_reset: int = 0
    reviews_reset: int = 0
    profiles_reset: int = 0
    test_tracked_remaining: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class PendingReviewInspectionService:
    """Backfill inspection for already-generated V2 items that are still pending.

    Design constraints:
    - completed reviews never enter the query;
    - reference images are never downloaded or saved;
    - Danbooru metadata is fetched lazily only for outfit-ambiguous outputs;
    - existing WD/quality infrastructure is reused instead of adding a local model;
    - regeneration is capped per character to prevent storage/API runaway;
    - high-confidence automatic ratings keep a deterministic audit sample pending.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings_service = SettingsService(db)

    def _latest_image_subquery(self):
        return (
            self.db.query(
                GlobalCharacterImage.global_character_id.label("character_id"),
                func.max(GlobalCharacterImage.id).label("image_id"),
            )
            .group_by(GlobalCharacterImage.global_character_id)
            .subquery()
        )

    @staticmethod
    def _needs_inspection_filter():
        """Return true only when the latest image has not completed the current checks.

        A quality reject intentionally skips identity checking, so a current quality
        reject is already fully inspected even though identity_checker_version is NULL.
        This prevents 0-star audit samples from re-entering the backfill forever.
        """
        return or_(
            GlobalCharacterImage.quality_checker_version.is_(None),
            GlobalCharacterImage.quality_checker_version != QUALITY_CHECKER_VERSION,
            and_(
                GlobalCharacterImage.quality_status != "reject",
                or_(
                    GlobalCharacterImage.identity_checker_version.is_(None),
                    GlobalCharacterImage.identity_checker_version != IDENTITY_CHECKER_VERSION,
                ),
            ),
        )

    def candidates(self, *, limit: int) -> list[tuple[GlobalCharacter, GlobalCharacterImage]]:
        latest = self._latest_image_subquery()
        return (
            self.db.query(GlobalCharacter, GlobalCharacterImage)
            .join(latest, latest.c.character_id == GlobalCharacter.id)
            .join(GlobalCharacterImage, GlobalCharacterImage.id == latest.c.image_id)
            .outerjoin(
                GlobalCharacterReview,
                GlobalCharacterReview.global_character_id == GlobalCharacter.id,
            )
            .filter(
                or_(
                    GlobalCharacterReview.id.is_(None),
                    GlobalCharacterReview.review_status == "pending",
                )
            )
            .filter(self._needs_inspection_filter())
            .order_by(GlobalCharacter.id.asc())
            .limit(max(1, min(limit, 500)))
            .all()
        )

    def stats(self) -> dict[str, int | str]:
        latest = self._latest_image_subquery()
        base = (
            self.db.query(GlobalCharacterImage)
            .join(latest, GlobalCharacterImage.id == latest.c.image_id)
            .join(GlobalCharacter, GlobalCharacter.id == latest.c.character_id)
            .outerjoin(
                GlobalCharacterReview,
                GlobalCharacterReview.global_character_id == GlobalCharacter.id,
            )
            .filter(
                or_(
                    GlobalCharacterReview.id.is_(None),
                    GlobalCharacterReview.review_status == "pending",
                )
            )
        )
        total = base.count()
        remaining = base.filter(self._needs_inspection_filter()).count()
        return {
            "inspection_version": PENDING_INSPECTION_VERSION,
            "quality_checker_version": QUALITY_CHECKER_VERSION,
            "identity_checker_version": IDENTITY_CHECKER_VERSION,
            "reference_profile_version": REFERENCE_PROFILE_VERSION,
            "pending_with_image": total,
            "remaining": remaining,
            "current": max(0, total - remaining),
            "test_tracked": len(self.tracked_test_character_ids()),
        }

    def tracked_test_character_ids(self) -> list[int]:
        return self.settings_service.get_pending_inspection_test_ids()

    def record_test_characters(self, character_ids: list[int]) -> list[int]:
        """Remember page-test targets in the DB so a reset survives UI state loss."""
        if not character_ids:
            return self.tracked_test_character_ids()
        merged = list(dict.fromkeys([*self.tracked_test_character_ids(), *character_ids]))
        # Keep the newest entries: the oldest page tests are the least likely to still
        # need a reset, and the list must stay small enough for one settings row.
        return self.settings_service.set_pending_inspection_test_ids(
            merged[-MAX_TRACKED_TEST_CHARACTERS:]
        )

    def forget_test_characters(self, character_ids: list[int]) -> list[int]:
        if not character_ids:
            return self.tracked_test_character_ids()
        done = set(character_ids)
        return self.settings_service.set_pending_inspection_test_ids(
            [tracked for tracked in self.tracked_test_character_ids() if tracked not in done]
        )

    def _inspect_existing(
        self,
        character: GlobalCharacter,
        image: GlobalCharacterImage,
    ) -> GlobalCharacterImage:
        return run_v2_quality_identity_checks(
            self.db,
            image,
            character,
            hf_token=self.settings_service.get_hf_token() or None,
            hf_wd_model=self.settings_service.get_hf_wd_model() or None,
        )

    @staticmethod
    def _candidate_from_reasons(image: GlobalCharacterImage) -> tuple[int | None, float | None]:
        try:
            reasons = json.loads(image.identity_reasons or "[]")
        except json.JSONDecodeError:
            return None, None
        for reason in reasons:
            text = str(reason)
            if not text.startswith("auto_rating_candidate:"):
                continue
            parts = text.split(":")
            if len(parts) != 3:
                continue
            try:
                return int(parts[1]), float(parts[2])
            except ValueError:
                continue
        return None, None

    @staticmethod
    def _is_audit_sample(character_id: int, rate: float) -> bool:
        bounded = max(0.0, min(rate, 1.0))
        if bounded <= 0:
            return False
        digest = hashlib.blake2b(
            f"{PENDING_INSPECTION_VERSION}:{character_id}".encode("utf-8"),
            digest_size=8,
        ).digest()
        bucket = int.from_bytes(digest, "big") / float(2**64 - 1)
        return bucket < bounded

    def _review_for(self, character: GlobalCharacter) -> GlobalCharacterReview:
        review = (
            self.db.query(GlobalCharacterReview)
            .filter(GlobalCharacterReview.global_character_id == character.id)
            .first()
        )
        if review is None:
            review = GlobalCharacterReview(
                global_character_id=character.id,
                review_status="pending",
                rating_stage="primary",
            )
            self.db.add(review)
            self.db.flush()
        return review

    @staticmethod
    def _append_auto_note(review: GlobalCharacterReview, marker: str) -> None:
        review.review_note = f"{review.review_note}\n{marker}".strip() if review.review_note else marker

    @staticmethod
    def _auto_marker_suffix(*, test_run: bool) -> str:
        return ";test=1" if test_run else ""

    @staticmethod
    def _auto_marker_fields(line: str) -> dict[str, str]:
        if not line.startswith("auto_inspection="):
            return {}
        fields: dict[str, str] = {}
        for part in line[len("auto_inspection=") :].split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
        return fields

    @classmethod
    def _is_test_auto_marker(cls, line: str) -> bool:
        if not line.startswith("auto_inspection="):
            return False
        return cls._auto_marker_fields(line).get("test") == "1"

    def _prefill_rating(
        self,
        character: GlobalCharacter,
        *,
        rating: int,
        confidence: float,
        reason: str,
        test_run: bool = False,
    ) -> bool:
        """Prefill a likely rating while leaving the item pending for one-key confirmation."""
        review = self._review_for(character)
        if review.rating is not None:
            return False
        review.rating = rating
        if review.gender is None:
            review.gender = character.gender
        self._append_auto_note(
            review,
            (
                f"auto_inspection={PENDING_INSPECTION_VERSION};prefill=1;rating={rating};"
                f"confidence={confidence:.2f};reason={reason}"
                f"{self._auto_marker_suffix(test_run=test_run)}"
            ),
        )
        self.db.flush()
        return True

    def _apply_auto_rating(
        self,
        character: GlobalCharacter,
        *,
        rating: int,
        confidence: float,
        audit_sample_rate: float,
        reason: str,
        test_run: bool = False,
    ) -> str:
        review = self._review_for(character)
        # Never overwrite an explicit pending user decision.
        if review.rating is not None:
            return "skipped"

        review.rating = rating
        if review.gender is None:
            review.gender = character.gender
        audit = self._is_audit_sample(character.id, audit_sample_rate)
        review.review_status = "pending" if audit else "completed"
        marker = (
            f"auto_inspection={PENDING_INSPECTION_VERSION};rating={rating};"
            f"confidence={confidence:.2f};audit={int(audit)};reason={reason}"
            f"{self._auto_marker_suffix(test_run=test_run)}"
        )
        self._append_auto_note(review, marker)
        if not audit:
            # The compact baseline is useful only while the character still needs
            # review/regeneration. Drop it as soon as automation completes the item.
            character.reference_profile = None
            character.reference_profile_version = None
            character.reference_profile_updated_at = None
        self.db.flush()
        return "audit" if audit else "completed"

    @staticmethod
    def _json_reason_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    def _regenerate_capped(
        self,
        character: GlobalCharacter,
        *,
        max_regenerations: int,
        external_stage_control: bool = False,
        repair_stage: str | None = None,
        identity_snapshot: IdentityCheckResult | None = None,
    ) -> tuple[V2PipelineResult | None, int]:
        attempts = max(1, max_regenerations)
        tracked_job = v2_generation_job_manager.start_inspection_regeneration(
            character.id,
            character_tag=character.character_tag,
            max_attempts=attempts,
        )
        if tracked_job is None:
            raise RuntimeError(f"{character.character_tag}: 재생성 작업이 이미 진행 중입니다.")

        pipeline = V2GenerationPipeline(self.db)
        if repair_stage in {
            STAGE_IDENTITY_HAIR,
            STAGE_IDENTITY_MULTICOLOR,
            STAGE_IDENTITY_EYE,
        }:
            variant = pipeline.build_stage_variant(
                character,
                stage=repair_stage,
                identity=identity_snapshot,
            )
            if variant is not None:
                pipeline.apply_variant_to_character(character, variant)

        state = pipeline.prepare_async_character(character.id)
        generated = 0
        try:
            for attempt in range(1, attempts + 1):
                if v2_generation_job_manager.is_inspection_regeneration_cancelled(tracked_job.job_id):
                    pipeline.cancel_async_character(state)
                    v2_generation_job_manager.finish_inspection_regeneration(
                        tracked_job.job_id,
                        status="cancelled",
                        message=f"자동 검사 재생성 취소 · {character.character_tag} · {generated}/{attempts}",
                    )
                    return None, generated

                v2_generation_job_manager.update_inspection_regeneration(
                    tracked_job.job_id,
                    phase="waiting",
                    message=f"자동 검사 재생성 준비 · {character.character_tag} · {generated}/{attempts}",
                )
                if not pipeline.wait_before_async_generation(
                    should_interrupt=lambda: v2_generation_job_manager.is_inspection_regeneration_cancelled(
                        tracked_job.job_id
                    )
                ):
                    pipeline.cancel_async_character(state)
                    v2_generation_job_manager.finish_inspection_regeneration(
                        tracked_job.job_id,
                        status="cancelled",
                        message=f"자동 검사 재생성 취소 · {character.character_tag} · {generated}/{attempts}",
                    )
                    return None, generated

                v2_generation_job_manager.update_inspection_regeneration(
                    tracked_job.job_id,
                    phase="generating",
                    message=(
                        f"자동 검사 재생성 · {character.character_tag}"
                        f"{f' · {repair_stage}' if repair_stage else ''}"
                        f" · {attempt}/{attempts}"
                    ),
                )
                image_id = pipeline.generate_async_attempt(
                    state,
                    should_cancel=lambda: v2_generation_job_manager.is_inspection_regeneration_cancelled(
                        tracked_job.job_id
                    ),
                )
                generated += 1
                v2_generation_job_manager.update_inspection_regeneration(
                    tracked_job.job_id,
                    phase="checking",
                    generated=generated,
                    message=f"재생성 이미지 검사 중 · {character.character_tag} · {generated}/{attempts}",
                )
                checked = pipeline.check_async_attempt(
                    state,
                    image_id,
                    external_stage_control=external_stage_control,
                )
                image = self.db.get(GlobalCharacterImage, image_id)
                self.db.refresh(character)
                v2_generation_job_manager.update_inspection_regeneration(
                    tracked_job.job_id,
                    current=generated,
                    generated=generated,
                    checks_completed=generated,
                    image_id=image_id,
                    quality_status=image.quality_status if image else None,
                    quality_reasons=self._json_reason_list(image.quality_reasons) if image else [],
                    identity_status=image.identity_status if image else None,
                    identity_reasons=self._json_reason_list(image.identity_reasons) if image else [],
                    is_provisional=image.is_provisional if image else None,
                    generation_status=character.generation_status,
                    generation_attempts=character.generation_attempts,
                    total_generation_attempts=character.total_generation_attempts,
                    last_failure_reason=character.last_failure_reason,
                )
                if checked.result is not None:
                    passed = checked.result.generation_status == "generated"
                    # Under external stage control a non-"generated" result is a normal
                    # hand-off to the outer stage loop (image was produced and inspected),
                    # not a real generation failure. Only exceptions/cancels are failures.
                    handoff = external_stage_control and generated > 0 and not passed
                    final_status = "completed" if (passed or handoff) else "failed"
                    stage_label = f" · {repair_stage}" if repair_stage else ""
                    if passed:
                        message = f"자동 검사 재생성 완료 · {character.character_tag}{stage_label} · {generated}/{attempts}"
                    elif handoff:
                        message = (
                            f"자동 검사 재생성 단계 완료 · {character.character_tag}{stage_label}"
                            f" · 다음 판정 대기 · {generated}/{attempts}"
                        )
                    else:
                        message = f"자동 검사 재생성 실패 · {character.character_tag}{stage_label} · {generated}/{attempts}"
                    v2_generation_job_manager.finish_inspection_regeneration(
                        tracked_job.job_id,
                        status=final_status,
                        message=message,
                        failure_reason=(None if final_status == "completed" else character.last_failure_reason),
                    )
                    return checked.result, generated
                if not checked.needs_generation:
                    v2_generation_job_manager.finish_inspection_regeneration(
                        tracked_job.job_id,
                        status="failed",
                        message=f"자동 검사 재생성 실패 · {character.character_tag} · {generated}/{attempts}",
                        failure_reason=character.last_failure_reason,
                    )
                    return None, generated

            pipeline.fail_async_character(state, "pending_inspection_regeneration_limit")
            self.db.refresh(character)
            v2_generation_job_manager.finish_inspection_regeneration(
                tracked_job.job_id,
                status="failed",
                message=f"자동 검사 재생성 제한 도달 · {character.character_tag} · {generated}/{attempts}",
                failure_reason="pending_inspection_regeneration_limit",
            )
            return None, generated
        except Exception as exc:
            pipeline.fail_async_character(state, "pending_inspection_regeneration_error")
            v2_generation_job_manager.finish_inspection_regeneration(
                tracked_job.job_id,
                status="failed",
                message=f"자동 검사 재생성 오류 · {character.character_tag}",
                failure_reason=str(exc),
            )
            raise

    def _latest_image_for(self, character_id: int) -> GlobalCharacterImage | None:
        return (
            self.db.query(GlobalCharacterImage)
            .filter(GlobalCharacterImage.global_character_id == character_id)
            .order_by(GlobalCharacterImage.id.desc())
            .first()
        )

    def _image_count_for(self, character_id: int) -> int:
        return (
            self.db.query(func.count(GlobalCharacterImage.id))
            .filter(GlobalCharacterImage.global_character_id == character_id)
            .scalar()
            or 0
        )

    @staticmethod
    def _identity_snapshot_from_image(image: GlobalCharacterImage) -> IdentityCheckResult:
        reasons = PendingReviewInspectionService._json_reason_list(image.identity_reasons)
        suggested = PendingReviewInspectionService._json_reason_list(image.suggested_multicolor_tags)
        return IdentityCheckResult(
            status=image.identity_status or "warning",
            character_confidence=image.character_confidence,
            hair_color_confidence=image.hair_color_confidence,
            conflicting_character_tag=image.conflicting_character_tag,
            conflicting_character_confidence=image.conflicting_character_confidence,
            reasons=reasons,
            suggested_multicolor_tags=suggested,
        )

    def _repair_with_stages(
        self,
        character: GlobalCharacter,
        image: GlobalCharacterImage,
        *,
        auto_regenerate: bool,
        max_regenerations: int,
        cleanup_rejected: bool,
        summary: PendingInspectionSummary,
    ) -> tuple[GlobalCharacterImage, RepairContext, bool]:
        """Identity-first repair loop with explicit reinspection of each new latest image."""
        context = RepairContext(
            latest_image_id=image.id,
            image_count=self._image_count_for(character.id),
        )
        current = image
        stage_budget = max(max_regenerations, MAX_STAGE_REGENERATIONS)
        auto_zero = False
        precheck_pipeline = V2GenerationPipeline(self.db)
        identity_stages = {STAGE_IDENTITY_HAIR, STAGE_IDENTITY_MULTICOLOR, STAGE_IDENTITY_EYE}

        while True:
            reasons = self._json_reason_list(current.identity_reasons)
            context.latest_image_id = current.id
            context.image_count = self._image_count_for(character.id)
            context.reject_reason = reasons[0] if reasons else None
            if is_tagger_failure(reasons):
                context.final_action = "manual"
                return current, context, False

            stage = decide_repair_stage(
                gender=character.gender,
                quality_status=current.quality_status,
                identity_status=current.identity_status,
                reasons=reasons,
                context=context,
            )

            if stage == STAGE_DONE:
                context.final_action = "pass"
                context.identity_ok = True
                return current, context, False

            if stage == STAGE_AUTO_ZERO:
                context.final_action = "0성"
                context.mark(STAGE_AUTO_ZERO)
                return current, context, True

            if not auto_regenerate:
                context.final_action = "manual"
                return current, context, False

            if context.regeneration_requested >= stage_budget:
                context.final_action = "0성"
                return current, context, True

            identity_snapshot = self._identity_snapshot_from_image(current)

            # Skip identity stages that have no actionable collected data. This must not
            # spend a regeneration on an unchanged prompt; marking the stage lets
            # decide_repair_stage advance to the next stage (or auto-zero).
            if stage in identity_stages:
                stage_variant = precheck_pipeline.build_stage_variant(
                    character, stage=stage, identity=identity_snapshot
                )
                if stage_variant is None:
                    context.mark_unavailable(stage)
                    context.record_event(
                        {
                            "stage": stage,
                            "status": "unavailable",
                            "before_base_prompt": character.base_prompt,
                        }
                    )
                    continue

            # Outer stage loop owns retry counts. Each stage job generates at most one
            # image; semantic/quality may run the stage itself up to twice via RepairContext.
            context.mark(stage)
            summary.regeneration_requested += 1
            context.regeneration_requested += 1
            before_prompt = character.base_prompt
            result, generated = self._regenerate_capped(
                character,
                max_regenerations=1,
                external_stage_control=True,
                repair_stage=stage,
                identity_snapshot=identity_snapshot,
            )
            summary.characters_regenerated += 1
            summary.regeneration_images += generated
            if generated:
                context.regeneration_completed += 1

            latest = self._latest_image_for(character.id)
            if latest is None:
                context.final_action = "0성"
                return current, context, True

            # New latest must be inspected even when the generation job already stamped
            # checker versions — force a fresh pass when the pipeline skipped identity
            # (quality reject) or left an older stamp somehow.
            if (
                latest.id != current.id
                or latest.identity_checker_version != IDENTITY_CHECKER_VERSION
                or (
                    latest.quality_status != "reject"
                    and latest.identity_status is None
                )
            ):
                if latest.quality_checker_version != QUALITY_CHECKER_VERSION or (
                    latest.quality_status != "reject"
                    and latest.identity_checker_version != IDENTITY_CHECKER_VERSION
                ):
                    latest = self._inspect_existing(character, latest)
                context.reinspection_completed += 1
                summary.inspected += 1
                self._record_inspection_diagnostics(summary, latest)

            if cleanup_rejected:
                summary.rejected_files_removed += self._cleanup_superseded_rejects(
                    character.id,
                    keep_image_id=latest.id,
                )

            self.db.refresh(character)
            context.record_event(
                {
                    "stage": stage,
                    "status": "regenerated",
                    "before_base_prompt": before_prompt,
                    "after_base_prompt": character.base_prompt,
                    "generated_image_id": latest.id,
                    "identity_status": latest.identity_status,
                    "identity_reasons": self._json_reason_list(latest.identity_reasons),
                    "pipeline_status": result.generation_status if result is not None else None,
                }
            )

            current = latest
            commit_db_session(self.db)

            if result is not None and result.generation_status == "generated":
                # Pipeline reported success; still re-evaluate stages in case a warning
                # identity repair remains (should be rare with external_stage_control).
                continue

            # generation_failed / cancelled / exhausted — let decide_repair_stage choose
            # the next identity/semantic stage or auto-zero on the reinpected latest.
            continue

        return current, context, auto_zero

    def _cleanup_superseded_rejects(self, character_id: int, *, keep_image_id: int) -> int:
        """Keep one latest result and remove older unselected rejects to cap storage growth."""
        rows = (
            self.db.query(GlobalCharacterImage)
            .filter(
                GlobalCharacterImage.global_character_id == character_id,
                GlobalCharacterImage.id != keep_image_id,
                GlobalCharacterImage.is_cover.is_(False),
                GlobalCharacterImage.is_provisional.is_(False),
                or_(
                    GlobalCharacterImage.quality_status == "reject",
                    GlobalCharacterImage.identity_status == "reject",
                ),
            )
            .all()
        )
        removed = 0
        for image in rows:
            path = settings.project_root / image.image_path
            if path.is_file():
                path.unlink()
            self.db.delete(image)
            removed += 1
        if removed:
            self.db.flush()
        return removed

    @staticmethod
    def _clear_image_inspection(image: GlobalCharacterImage) -> None:
        image.quality_status = None
        image.quality_score = None
        image.quality_reasons = None
        image.quality_checked_at = None
        image.quality_checker_version = None
        image.identity_status = None
        image.character_confidence = None
        image.hair_color_confidence = None
        image.conflicting_character_tag = None
        image.conflicting_character_confidence = None
        image.identity_reasons = None
        image.suggested_multicolor_tags = None
        image.identity_checked_at = None
        image.identity_checker_version = None
        image.is_provisional = False

    def reset_test_results(self, character_ids: list[int]) -> PendingInspectionResetSummary:
        """Clear inspection metadata for explicitly tracked page-test characters only.

        Generated image files are intentionally preserved. Automatic review decisions are
        reverted only for `auto_inspection=...;test=1` markers. Non-test automation notes
        and ratings that no longer match the test marker (user edits) are left alone.
        """
        ids = list(dict.fromkeys(character_id for character_id in character_ids if character_id > 0))[
            :MAX_RESET_CHARACTERS
        ]
        summary = PendingInspectionResetSummary(requested=len(ids))
        if not ids:
            return summary

        latest = self._latest_image_subquery()
        rows = (
            self.db.query(GlobalCharacter, GlobalCharacterImage)
            .join(latest, latest.c.character_id == GlobalCharacter.id)
            .join(GlobalCharacterImage, GlobalCharacterImage.id == latest.c.image_id)
            .filter(GlobalCharacter.id.in_(ids))
            .all()
        )
        summary.matched = len(rows)

        for character, image in rows:
            self._clear_image_inspection(image)
            summary.images_reset += 1

            if (
                character.reference_profile is not None
                or character.reference_profile_version is not None
                or character.reference_profile_updated_at is not None
            ):
                character.reference_profile = None
                character.reference_profile_version = None
                character.reference_profile_updated_at = None
                summary.profiles_reset += 1

            review = (
                self.db.query(GlobalCharacterReview)
                .filter(GlobalCharacterReview.global_character_id == character.id)
                .first()
            )
            if review is None or not review.review_note:
                continue

            lines = [line for line in review.review_note.splitlines() if line.strip()]
            test_lines = [line for line in lines if self._is_test_auto_marker(line)]
            if not test_lines:
                continue

            marker_ratings: set[int] = set()
            for line in test_lines:
                fields = self._auto_marker_fields(line)
                raw_rating = fields.get("rating")
                if raw_rating is not None:
                    try:
                        marker_ratings.add(int(raw_rating))
                    except ValueError:
                        pass

            review.review_note = "\n".join(line for line in lines if line not in test_lines) or None
            # Only undo the value automation itself wrote. If the user changed rating
            # after the test, current rating will differ from the marker and is kept.
            if review.rating is not None and review.rating in marker_ratings:
                review.rating = None
                review.review_status = "pending"
            summary.reviews_reset += 1

        commit_db_session(self.db)
        self.forget_test_characters(ids)
        summary.test_tracked_remaining = len(self.tracked_test_character_ids())
        return summary

    def _record_inspection_diagnostics(
        self,
        summary: PendingInspectionSummary,
        image: GlobalCharacterImage,
    ) -> None:
        reasons = self._json_reason_list(image.identity_reasons)
        if is_tagger_failure(reasons):
            summary.tagger_error += 1
            return
        if image.identity_checker_version:
            summary.tagger_success += 1
        if image.identity_status == "reject" or image.quality_status == "reject":
            summary.semantic_reject += 1
        elif image.identity_status == "warning" or image.quality_status == "warning":
            summary.semantic_warning += 1
        elif image.identity_status == "pass" and image.quality_status == "pass":
            summary.semantic_pass += 1
        if any(str(reason).startswith("reference_") for reason in reasons):
            if any(
                str(reason) in {"reference_fetch_failed", "reference_insufficient"}
                for reason in reasons
            ):
                summary.reference_failed += 1
            elif any(str(reason) == "reference_loaded" for reason in reasons):
                summary.reference_loaded += 1

    def inspect_batch(
        self,
        *,
        limit: int = 50,
        auto_regenerate: bool = True,
        max_regenerations: int = DEFAULT_MAX_REGENERATIONS,
        auto_complete: bool = True,
        audit_sample_rate: float = DEFAULT_AUDIT_SAMPLE_RATE,
        cleanup_rejected: bool = True,
        test_run: bool = False,
    ) -> PendingInspectionSummary:
        summary = PendingInspectionSummary(requested_limit=limit)
        candidates = self.candidates(limit=limit)

        for character, image in candidates:
            try:
                # Re-check the review state immediately before a potentially expensive call.
                review = (
                    self.db.query(GlobalCharacterReview)
                    .filter(GlobalCharacterReview.global_character_id == character.id)
                    .first()
                )
                if review is not None and review.review_status != "pending":
                    continue

                checked = self._inspect_existing(character, image)
                summary.inspected += 1
                summary.inspected_character_ids.append(character.id)
                self._record_inspection_diagnostics(summary, checked)
                commit_db_session(self.db)

                was_reject = checked.quality_status == "reject" or checked.identity_status == "reject"
                reasons = self._json_reason_list(checked.identity_reasons)
                needs_repair = (
                    was_reject
                    or needs_identity_repair(reasons)
                    or identity_insufficient(reasons)
                )

                final_image = checked
                regeneration_exhausted = False
                repair_context: RepairContext | None = None

                if needs_repair and not is_tagger_failure(reasons):
                    if was_reject:
                        summary.rejected += 1
                    elif checked.quality_status == "warning" or checked.identity_status == "warning":
                        summary.warnings += 1

                    final_image, repair_context, auto_zero = self._repair_with_stages(
                        character,
                        checked,
                        auto_regenerate=auto_regenerate,
                        max_regenerations=max_regenerations,
                        cleanup_rejected=cleanup_rejected,
                        summary=summary,
                    )
                    regeneration_exhausted = auto_zero or repair_context.final_action == "0성"
                    if repair_context.final_action == "pass":
                        summary.passed += 1
                elif checked.quality_status == "warning" or checked.identity_status == "warning":
                    summary.warnings += 1
                    repair_context = RepairContext(
                        latest_image_id=checked.id,
                        image_count=self._image_count_for(character.id),
                        final_action="pass",
                        identity_ok=not identity_insufficient(reasons),
                        reject_reason=reasons[0] if reasons else None,
                    )
                else:
                    summary.passed += 1
                    repair_context = RepairContext(
                        latest_image_id=checked.id,
                        image_count=self._image_count_for(character.id),
                        final_action="pass",
                        identity_ok=True,
                    )

                if repair_context is not None:
                    summary.character_diagnostics.append(
                        {
                            "character_id": character.id,
                            "character_tag": character.character_tag,
                            "inspected": True,
                            **repair_context.as_dict(),
                        }
                    )

                rating, confidence = self._candidate_from_reasons(final_image)
                if rating == 3 and confidence is not None and confidence >= PREFILL_RATING_CONFIDENCE:
                    # 3 is never auto-completed: prefill it so normal female results
                    # usually need only Enter while favorites can still be promoted.
                    if self._prefill_rating(
                        character,
                        rating=3,
                        confidence=confidence,
                        reason="confident_female_output",
                        test_run=test_run,
                    ):
                        summary.prefilled_pending += 1
                    summary.suggested_only += 1
                elif rating in {-1, 1} and confidence is not None:
                    if auto_complete and confidence >= AUTO_RATING_CONFIDENCE:
                        outcome = self._apply_auto_rating(
                            character,
                            rating=rating,
                            confidence=confidence,
                            audit_sample_rate=audit_sample_rate,
                            reason="local_prior_and_output_agree",
                            test_run=test_run,
                        )
                        if outcome == "completed":
                            summary.auto_completed += 1
                        elif outcome == "audit":
                            summary.audit_kept_pending += 1
                        if outcome in {"completed", "audit"}:
                            key = str(rating)
                            summary.ratings[key] = summary.ratings.get(key, 0) + 1
                    elif confidence >= PREFILL_RATING_CONFIDENCE:
                        if self._prefill_rating(
                            character,
                            rating=rating,
                            confidence=confidence,
                            reason="conservative_rating_prefill",
                            test_run=test_run,
                        ):
                            summary.prefilled_pending += 1

                if auto_complete and auto_regenerate and regeneration_exhausted:
                    # 0-star is automatic only when this inspection run actually
                    # exhausted its capped regeneration budget. Do not reuse a stale
                    # generation_failed state from an earlier run/reset.
                    outcome = self._apply_auto_rating(
                        character,
                        rating=0,
                        confidence=1.0,
                        audit_sample_rate=audit_sample_rate,
                        reason="regeneration_limit_exhausted",
                        test_run=test_run,
                    )
                    if outcome == "completed":
                        summary.auto_completed += 1
                    elif outcome == "audit":
                        summary.audit_kept_pending += 1
                    if outcome in {"completed", "audit"}:
                        summary.ratings["0"] = summary.ratings.get("0", 0) + 1

                commit_db_session(self.db)
            except Exception as exc:
                self.db.rollback()
                summary.errors.append(f"{character.character_tag}: {exc}")

        if test_run:
            self.record_test_characters(summary.inspected_character_ids)

        return summary
