from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.integrations.image_tagger.hf_wd_tagger import (
    HFWdTaggerError,
    assert_wd_tagger_ready,
    local_wd_available,
)
from app.services.identity_checker import IDENTITY_CHECKER_VERSION
from app.services.pending_review_inspection_service import (
    LOCAL_REVIEW_STATUSES,
    MAX_RESET_CHARACTERS,
    PendingReviewInspectionService,
)
from app.services.quality_checker import QUALITY_CHECKER_VERSION
from app.services.review_service import ReviewService
from app.services.settings_service import SettingsService
from app.services.v2_generation_job_manager import v2_generation_job_manager

router = APIRouter(prefix="/review/v2/pending-inspection", tags=["review-v2-inspection"])


class PendingInspectionSelection(BaseModel):
    character_ids: list[int]


class PendingInspectionResetSelection(BaseModel):
    # Empty means "use the character ids this server recorded during page tests".
    character_ids: list[int] = []


class LocalReviewRequest(BaseModel):
    character_id: int
    status: str
    note: str | None = None


class LocalReviewResponse(BaseModel):
    character_id: int
    local_review: str


def _active_v2_generation_exists() -> bool:
    return any(
        job.status in {"queued", "running", "paused"}
        for job in v2_generation_job_manager.list_visible_jobs(limit=100)
    )


def _assert_inspection_ready(db: Session) -> None:
    settings_service = SettingsService(db)
    hf_token = settings_service.get_hf_token() or None
    hf_model = settings_service.get_hf_wd_model() or None
    try:
        assert_wd_tagger_ready(hf_token=hf_token, model=hf_model or "SmilingWolf/wd-eva02-large-tagger-v3")
    except HFWdTaggerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not hf_token and not local_wd_available():
        raise HTTPException(
            status_code=409,
            detail="Pending 자동 검사는 로컬 WD ONNX 또는 Settings의 Hugging Face Token이 필요합니다.",
        )
    if _active_v2_generation_exists():
        # The inspector may call NAIA for rejected items. Never compete with the normal
        # V2 generation queue: keeping a single producer is both cheaper and safer for
        # SQLite/NAIA on a laptop.
        raise HTTPException(
            status_code=409,
            detail="V2 생성/재생성 작업이 진행 중입니다. 완료 후 Pending 자동 검사를 실행하세요.",
        )


def _selected_candidates(
    db: Session,
    character_ids: list[int],
    *,
    force_recheck: bool = False,
) -> list[tuple[GlobalCharacter, GlobalCharacterImage]]:
    """Return pending rows for an explicit UI page selection.

    Production incremental runs skip images already on the current checker versions.
    Page tests pass force_recheck=True so algorithm changes can be validated against
    the currently visible cards even after a prior pass.
    """
    ids = list(dict.fromkeys(character_id for character_id in character_ids if character_id > 0))[:30]
    if not ids:
        return []

    latest = (
        db.query(
            GlobalCharacterImage.global_character_id.label("character_id"),
            func.max(GlobalCharacterImage.id).label("image_id"),
        )
        .filter(GlobalCharacterImage.global_character_id.in_(ids))
        .group_by(GlobalCharacterImage.global_character_id)
        .subquery()
    )
    query = (
        db.query(GlobalCharacter, GlobalCharacterImage)
        .join(latest, latest.c.character_id == GlobalCharacter.id)
        .join(GlobalCharacterImage, GlobalCharacterImage.id == latest.c.image_id)
        .outerjoin(
            GlobalCharacterReview,
            GlobalCharacterReview.global_character_id == GlobalCharacter.id,
        )
        .filter(GlobalCharacter.id.in_(ids))
        .filter(
            or_(
                GlobalCharacterReview.id.is_(None),
                GlobalCharacterReview.review_status == "pending",
            )
        )
    )
    if not force_recheck:
        query = query.filter(
            or_(
                GlobalCharacterImage.quality_checker_version.is_(None),
                GlobalCharacterImage.quality_checker_version != QUALITY_CHECKER_VERSION,
                GlobalCharacterImage.identity_checker_version.is_(None),
                GlobalCharacterImage.identity_checker_version != IDENTITY_CHECKER_VERSION,
            )
        )
    return query.order_by(GlobalCharacter.id.asc()).all()


@router.get("/stats")
def pending_inspection_stats(db: Session = Depends(get_db)):
    """Return lightweight counts and make the review/inspection scopes explicit."""
    stats = PendingReviewInspectionService(db).stats()
    review_stats = ReviewService(db).get_v2_review_stats()
    pending_total = int(review_stats.get("pending", 0))
    pending_with_image = int(stats.get("pending_with_image", 0))
    return {
        **stats,
        "pending_total": pending_total,
        "pending_without_image": max(0, pending_total - pending_with_image),
    }


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
    _assert_inspection_ready(db)

    summary = PendingReviewInspectionService(db).inspect_batch(
        limit=limit,
        auto_regenerate=auto_regenerate,
        max_regenerations=max_regenerations,
        auto_complete=auto_complete,
        audit_sample_rate=audit_sample_rate,
        cleanup_rejected=cleanup_rejected,
    )
    return summary.as_dict()


@router.post("/run-selected")
def run_selected_pending_inspection(
    payload: PendingInspectionSelection,
    auto_regenerate: bool = Query(default=True),
    max_regenerations: int = Query(default=2, ge=1, le=5),
    auto_complete: bool = Query(default=True),
    audit_sample_rate: float = Query(default=0.10, ge=0.0, le=1.0),
    cleanup_rejected: bool = Query(default=True),
    force_recheck: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Inspect at most 30 explicitly selected characters, intended for current-page testing.

    force_recheck defaults to True so page tests re-run the current algorithm even when
    checker versions are already stamped. Production /run keeps incremental skipping.
    """
    selected_ids = list(dict.fromkeys(character_id for character_id in payload.character_ids if character_id > 0))
    if not selected_ids:
        raise HTTPException(status_code=400, detail="검사할 현재 페이지 항목이 없습니다.")
    if len(selected_ids) > 30:
        raise HTTPException(status_code=400, detail="현재 페이지 테스트는 한 번에 최대 30개까지 가능합니다.")

    rows = _selected_candidates(db, selected_ids, force_recheck=force_recheck)
    skipped_current_version = max(0, len(selected_ids) - len(rows)) if not force_recheck else 0
    if not rows:
        service = PendingReviewInspectionService(db)
        service.candidates = lambda *, limit: []  # type: ignore[method-assign]
        result = service.inspect_batch(limit=len(selected_ids), test_run=True).as_dict()
        result["skipped_current_version"] = skipped_current_version
        return result

    _assert_inspection_ready(db)
    service = PendingReviewInspectionService(db)
    # Reuse the exact production inspection workflow while constraining only the
    # candidate source to the IDs visible on the current page.
    service.candidates = lambda *, limit: rows[:limit]  # type: ignore[method-assign]
    summary = service.inspect_batch(
        limit=len(selected_ids),
        auto_regenerate=auto_regenerate,
        max_regenerations=max_regenerations,
        auto_complete=auto_complete,
        audit_sample_rate=audit_sample_rate,
        cleanup_rejected=cleanup_rejected,
        test_run=True,
    )
    result = summary.as_dict()
    result["skipped_current_version"] = skipped_current_version
    return result


@router.post("/local-review", response_model=LocalReviewResponse)
def record_local_review(
    payload: LocalReviewRequest,
    db: Session = Depends(get_db),
):
    """Store a local worker's first-pass confirmation for a suspect/0/-1 item (§7)."""
    if payload.status not in LOCAL_REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {', '.join(sorted(LOCAL_REVIEW_STATUSES))}",
        )
    character = db.query(GlobalCharacter).filter(GlobalCharacter.id == payload.character_id).first()
    if character is None:
        raise HTTPException(status_code=404, detail="캐릭터를 찾을 수 없습니다.")
    service = PendingReviewInspectionService(db)
    status = service.set_local_review(character, status=payload.status, note=payload.note)
    db.commit()
    return LocalReviewResponse(character_id=character.id, local_review=status)


@router.post("/reset-selected")
def reset_selected_pending_inspection(
    payload: PendingInspectionResetSelection,
    db: Session = Depends(get_db),
):
    """Temporarily reset metadata produced while validating the page-test workflow.

    The generated image files are kept. Only current checker metadata, compact reference
    profile data, and review decisions carrying an `auto_inspection=...;test=1` marker are
    reverted. When the client sends no ids the server-recorded page-test targets are used,
    so a browser reload cannot strand the reset.
    """
    service = PendingReviewInspectionService(db)
    selected_ids = list(dict.fromkeys(character_id for character_id in payload.character_ids if character_id > 0))
    if len(selected_ids) > MAX_RESET_CHARACTERS:
        raise HTTPException(status_code=400, detail="테스트 초기화는 한 번에 최대 1000개까지 가능합니다.")
    if not selected_ids:
        selected_ids = service.tracked_test_character_ids()[:MAX_RESET_CHARACTERS]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="초기화할 테스트 항목이 없습니다.")
    if _active_v2_generation_exists():
        raise HTTPException(
            status_code=409,
            detail="V2 생성/재생성 작업이 진행 중입니다. 완료 후 테스트 결과를 초기화하세요.",
        )

    summary = service.reset_test_results(selected_ids)
    return summary.as_dict()