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
from app.services.identity_checker import IDENTITY_CHECKER_VERSION
from app.services.quality_checker import QUALITY_CHECKER_VERSION
from app.services.reference_profile_service import REFERENCE_PROFILE_VERSION
from app.services.settings_service import SettingsService
from app.services.v2_generation_pipeline import V2GenerationPipeline, V2PipelineResult

PENDING_INSPECTION_VERSION = "v1.2"
AUTO_RATING_CONFIDENCE = 0.85
PREFILL_RATING_CONFIDENCE = 0.72
DEFAULT_AUDIT_SAMPLE_RATE = 0.10
DEFAULT_MAX_REGENERATIONS = 2


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

    def as_dict(self) -> dict[str, object]:
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
        }

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

    def _prefill_rating(
        self,
        character: GlobalCharacter,
        *,
        rating: int,
        confidence: float,
        reason: str,
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

    def _regenerate_capped(
        self,
        character: GlobalCharacter,
        *,
        max_regenerations: int,
    ) -> tuple[V2PipelineResult | None, int]:
        pipeline = V2GenerationPipeline(self.db)
        state = pipeline.prepare_async_character(character.id)
        generated = 0
        try:
            for _ in range(max(1, max_regenerations)):
                if not pipeline.wait_before_async_generation(should_interrupt=lambda: False):
                    break
                image_id = pipeline.generate_async_attempt(state, should_cancel=lambda: False)
                generated += 1
                checked = pipeline.check_async_attempt(state, image_id)
                if checked.result is not None:
                    return checked.result, generated
                if not checked.needs_generation:
                    return None, generated
            pipeline.fail_async_character(state, "pending_inspection_regeneration_limit")
            return None, generated
        except Exception:
            pipeline.fail_async_character(state, "pending_inspection_regeneration_error")
            raise

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

    def inspect_batch(
        self,
        *,
        limit: int = 50,
        auto_regenerate: bool = True,
        max_regenerations: int = DEFAULT_MAX_REGENERATIONS,
        auto_complete: bool = True,
        audit_sample_rate: float = DEFAULT_AUDIT_SAMPLE_RATE,
        cleanup_rejected: bool = True,
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
                commit_db_session(self.db)

                final_image = checked
                was_reject = checked.quality_status == "reject" or checked.identity_status == "reject"
                if was_reject:
                    summary.rejected += 1
                    if auto_regenerate:
                        result, generated = self._regenerate_capped(
                            character,
                            max_regenerations=max_regenerations,
                        )
                        summary.characters_regenerated += 1
                        summary.regeneration_images += generated
                        commit_db_session(self.db)
                        latest = (
                            self.db.query(GlobalCharacterImage)
                            .filter(GlobalCharacterImage.global_character_id == character.id)
                            .order_by(GlobalCharacterImage.id.desc())
                            .first()
                        )
                        if latest is not None:
                            final_image = latest
                            if cleanup_rejected:
                                summary.rejected_files_removed += self._cleanup_superseded_rejects(
                                    character.id,
                                    keep_image_id=final_image.id,
                                )
                        _ = result
                elif checked.quality_status == "warning" or checked.identity_status == "warning":
                    summary.warnings += 1
                else:
                    summary.passed += 1

                rating, confidence = self._candidate_from_reasons(final_image)
                if rating == 3 and confidence is not None and confidence >= PREFILL_RATING_CONFIDENCE:
                    # 3 is never auto-completed: prefill it so normal female results
                    # usually need only Enter while favorites can still be promoted.
                    if self._prefill_rating(
                        character,
                        rating=3,
                        confidence=confidence,
                        reason="confident_female_output",
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
                        ):
                            summary.prefilled_pending += 1

                if (
                    auto_complete
                    and auto_regenerate
                    and character.generation_status == "generation_failed"
                ):
                    # 0-star is only automatic after the capped regeneration path is
                    # exhausted. A deterministic 10% sample still remains in pending.
                    outcome = self._apply_auto_rating(
                        character,
                        rating=0,
                        confidence=1.0,
                        audit_sample_rate=audit_sample_rate,
                        reason="regeneration_limit_exhausted",
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

        return summary
