from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.pending_review_inspection_service import PendingReviewInspectionService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/review/v2/pending-inspection", tags=["review-v2-inspection"])


@router.get("/stats")
def pending_inspection_stats(db: Session = Depends(get_db)):
    """Return only lightweight DB counts; no image or Danbooru work is performed."""
    return PendingReviewInspectionService(db).stats()


@router.post("/run")
def run_pending_inspection(
    limit: int = Query(default=50, ge=1, le=500),
    auto_regenerate: bool = Query(default=True),
    max_regenerations: int = Query(default=2, ge=1, le=5),
    auto_complete: bool = Query(default=True),
    audit_sample_rate: float = Query(default=0.10, ge=0.0, le=1.0),
    cleanup_rejected: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Inspect one bounded batch of existing pending V2 images.

    Completed reviews are never selected. Failed images can be regenerated through the
    existing V2 pipeline, with a hard cap to prevent runaway API/storage use.
    """
    if not SettingsService(db).get_hf_token():
        # Without WD output the new semantic rules cannot run. Refuse the batch instead
        # of stamping every image as "checked" with tagger_unavailable and silently
        # preventing a later real backfill.
        raise HTTPException(
            status_code=409,
            detail="Pending 자동 검사는 Settings의 Hugging Face Token이 필요합니다.",
        )

    summary = PendingReviewInspectionService(db).inspect_batch(
        limit=limit,
        auto_regenerate=auto_regenerate,
        max_regenerations=max_regenerations,
        auto_complete=auto_complete,
        audit_sample_rate=audit_sample_rate,
        cleanup_rejected=cleanup_rejected,
    )
    return summary.as_dict()
