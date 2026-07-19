from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.schemas.character_catalog import (
    CatalogCollectAllRequest,
    CatalogJobListResponse,
    CatalogJobResponse,
    CatalogListStartRequest,
    CatalogRetryFailedRequest,
    CatalogTagsStartRequest,
    CharacterCreateRequest,
    CharacterLinkCandidate,
    CharacterLinkCandidateListResponse,
    CharacterLinkRequest,
    CharacterLinkResponse,
    CharacterUnlinkResponse,
    GlobalCharacterImageResponse,
    GlobalCharacterImagesResponse,
    GlobalCharacterListResponse,
    GlobalCharacterResponse,
)
from app.schemas.tag_relevance import (
    AppearanceTagRelevanceListResponse,
    RelevanceCollectJobResponse,
    RelevanceCollectStartRequest,
)
from app.services.character_catalog_job_manager import character_catalog_job_manager
from app.services.character_catalog_service import CharacterCatalogService
from app.services.character_link_service import CharacterLinkService, similarity_score
from app.services.relevance_collect_job_manager import relevance_collect_job_manager
from app.services.tag_relevance_service import TagRelevanceService

router = APIRouter(prefix="/character-catalog", tags=["character-catalog"])


def get_catalog_service(db: Session = Depends(get_db)) -> CharacterCatalogService:
    return CharacterCatalogService(db)


def get_link_service(db: Session = Depends(get_db)) -> CharacterLinkService:
    return CharacterLinkService(db)


def _require_danbooru() -> None:
    if not settings.danbooru_configured:
        raise HTTPException(status_code=400, detail="Configure Danbooru credentials in input/danbooru.env first.")


@router.post("/relevance/start", response_model=RelevanceCollectJobResponse)
def start_relevance_collect(
    payload: RelevanceCollectStartRequest,
    db: Session = Depends(get_db),
):
    _require_danbooru()
    if payload.target == "selected":
        character_ids = list(dict.fromkeys(payload.character_ids or []))
        if not character_ids:
            raise HTTPException(status_code=400, detail="character_ids must not be empty")
        found_ids = {
            row[0]
            for row in db.query(GlobalCharacter.id)
            .filter(GlobalCharacter.id.in_(character_ids))
            .all()
        }
        missing = [character_id for character_id in character_ids if character_id not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"Character not found: {missing[0]}")
    elif payload.target == "min_posts":
        if payload.min_post_count is None:
            raise HTTPException(status_code=400, detail="min_post_count is required for min_posts target")
        character_ids = TagRelevanceService(db).list_uncollected_ids(min_post_count=payload.min_post_count)
    else:  # "uncollected"
        character_ids = TagRelevanceService(db).list_uncollected_ids()

    if not character_ids:
        raise HTTPException(status_code=404, detail="No characters to collect")
    job = relevance_collect_job_manager.start(character_ids)
    return RelevanceCollectJobResponse.from_state(job)


@router.get("/relevance/jobs/{job_id}", response_model=RelevanceCollectJobResponse)
def get_relevance_collect_job(job_id: str):
    job = relevance_collect_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Relevance collect job not found")
    return RelevanceCollectJobResponse.from_state(job)


@router.post("/relevance/jobs/{job_id}/cancel", response_model=RelevanceCollectJobResponse)
def cancel_relevance_collect_job(job_id: str):
    job = relevance_collect_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Relevance collect job not found")
    if job.status == "cancelled":
        return RelevanceCollectJobResponse.from_state(job)
    if not relevance_collect_job_manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="Job cannot be cancelled")
    job = relevance_collect_job_manager.get_job(job_id)
    return RelevanceCollectJobResponse.from_state(job)


@router.post("/relevance/jobs/{job_id}/pause", response_model=RelevanceCollectJobResponse)
def pause_relevance_collect_job(job_id: str):
    job = relevance_collect_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Relevance collect job not found")
    if job.status != "running":
        raise HTTPException(status_code=400, detail="Only running jobs can be paused")
    relevance_collect_job_manager.pause(job_id)
    job = relevance_collect_job_manager.get_job(job_id)
    return RelevanceCollectJobResponse.from_state(job)


@router.post("/relevance/jobs/{job_id}/resume", response_model=RelevanceCollectJobResponse)
def resume_relevance_collect_job(job_id: str):
    job = relevance_collect_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Relevance collect job not found")
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    relevance_collect_job_manager.resume(job_id)
    job = relevance_collect_job_manager.get_job(job_id)
    return RelevanceCollectJobResponse.from_state(job)


@router.get(
    "/characters/{character_id}/relevance",
    response_model=AppearanceTagRelevanceListResponse,
)
def list_character_relevance(character_id: int, db: Session = Depends(get_db)):
    exists = db.query(GlobalCharacter.id).filter(GlobalCharacter.id == character_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Character not found")
    rows = TagRelevanceService(db).list_for_character(character_id)
    return AppearanceTagRelevanceListResponse(items=rows)


@router.get("/characters", response_model=GlobalCharacterListResponse)
def list_global_characters(
    search: str | None = None,
    gender: str | None = None,
    collect_status: str | None = None,
    series_id: int | None = Query(default=None, ge=1),
    min_post_count: int | None = Query(default=None, ge=0),
    max_post_count: int | None = Query(default=None, ge=0),
    has_image: bool | None = Query(default=None),
    has_cover: bool | None = Query(default=None),
    is_alternative: bool | None = Query(default=None),
    sort_by: str = Query(default="post_count"),
    sort_order: str = Query(default="desc"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    rows, total = service.list_characters(
        search=search,
        gender=gender,
        collect_status=collect_status,
        series_id=series_id,
        min_post_count=min_post_count,
        max_post_count=max_post_count,
        has_image=has_image,
        has_cover=has_cover,
        is_alternative=is_alternative,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return GlobalCharacterListResponse(
        items=[GlobalCharacterResponse.from_model(row) for row in rows],
        total=total,
    )


@router.post("/characters", response_model=GlobalCharacterResponse)
def create_global_character(
    payload: CharacterCreateRequest,
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    """캐릭터 탭에서 태그 하나만 입력해 개별 추가. 생성 후 곧바로 통합 태그
    수집(외형/성별/시리즈 + post_count)을 백그라운드 job으로 시작한다."""
    _require_danbooru()
    try:
        character = service.create_character(payload.character_tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    character_catalog_job_manager.start_catalog_tags([character.id])
    return GlobalCharacterResponse.from_model(character)


@router.get("/characters/{character_id}", response_model=GlobalCharacterResponse)
def get_global_character(character_id: int, service: CharacterCatalogService = Depends(get_catalog_service)):
    character = service.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return GlobalCharacterResponse.from_model(character)


@router.get("/characters/{character_id}/images", response_model=GlobalCharacterImagesResponse)
def get_global_character_images(character_id: int, service: CharacterCatalogService = Depends(get_catalog_service)):
    """캐릭터 탭 '이미지 보기' 팝업용. 커버가 선택되어 있으면 1장, 아니면 최근
    생성된 이미지 최대 2장을 반환한다."""
    character = service.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    images = service.get_character_images(character_id)
    return GlobalCharacterImagesResponse(
        id=character_id,
        images=[
            GlobalCharacterImageResponse(
                id=image.id,
                image_path=image.image_path,
                is_cover=image.is_cover,
                auto_status=image.auto_status,
            )
            for image in images
        ],
    )


@router.get("/characters/{character_id}/link/candidates", response_model=CharacterLinkCandidateListResponse)
def list_character_link_candidates(
    character_id: int,
    mode: str = Query(default="parent", pattern="^(parent|child)$"),
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    exclude_ids: str | None = Query(
        default=None,
        description="Comma-separated character IDs to exclude from candidates",
    ),
    service: CharacterCatalogService = Depends(get_catalog_service),
    link_service: CharacterLinkService = Depends(get_link_service),
):
    character = service.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    excluded: set[int] = set()
    if exclude_ids:
        for part in exclude_ids.split(","):
            part = part.strip()
            if part.isdigit():
                excluded.add(int(part))

    if mode == "parent":
        ranked = link_service.list_parent_candidates(character, search=search, limit=limit, exclude_ids=excluded or None)
    else:
        ranked = link_service.list_child_candidates(character, search=search, limit=limit, exclude_ids=excluded or None)

    role = "parent" if mode == "parent" else "child"
    candidates = [item.character for item in ranked]
    reason_map = {item.character.id: item.match_reason for item in ranked}

    # 후보들의 리뷰 상태/이미지 수/커버 경로를 한 번에 조회해 병합 판단에 필요한
    # 정보(이미 생성·선택된 캐릭터인지)를 배지로 보여줄 수 있게 한다.
    db = service.db
    candidate_ids = [item.id for item in candidates]
    review_map: dict[int, GlobalCharacterReview] = {}
    image_count_map: dict[int, int] = {}
    cover_path_map: dict[int, str] = {}
    if candidate_ids:
        reviews = (
            db.query(GlobalCharacterReview)
            .filter(GlobalCharacterReview.global_character_id.in_(candidate_ids))
            .all()
        )
        review_map = {review.global_character_id: review for review in reviews}
        image_count_map = dict(
            db.query(GlobalCharacterImage.global_character_id, func.count(GlobalCharacterImage.id))
            .filter(GlobalCharacterImage.global_character_id.in_(candidate_ids))
            .group_by(GlobalCharacterImage.global_character_id)
            .all()
        )
        cover_ids = {
            review.cover_image_id
            for review in reviews
            if review.cover_image_id and review.review_status == "completed"
        }
        if cover_ids:
            cover_images = (
                db.query(GlobalCharacterImage).filter(GlobalCharacterImage.id.in_(cover_ids)).all()
            )
            path_by_image_id = {image.id: image.image_path for image in cover_images}
            for review in reviews:
                if review.review_status == "completed" and review.cover_image_id in path_by_image_id:
                    cover_path_map[review.global_character_id] = path_by_image_id[review.cover_image_id]

    return CharacterLinkCandidateListResponse(
        items=[
            CharacterLinkCandidate(
                id=item.id,
                character_tag=item.character_tag,
                display_name=item.display_name,
                post_count=item.post_count,
                similarity_score=similarity_score(character, item),
                match_reason=reason_map.get(item.id) or None,
                linkable=link_service.candidate_is_linkable(item, role=role),
                review_status=review_map[item.id].review_status if item.id in review_map else None,
                rating=review_map[item.id].rating if item.id in review_map else None,
                image_count=image_count_map.get(item.id, 0),
                cover_image_path=cover_path_map.get(item.id),
            )
            for item in candidates
        ]
    )


@router.post("/characters/{character_id}/link", response_model=CharacterLinkResponse)
def link_character_to_parent(
    character_id: int,
    payload: CharacterLinkRequest,
    link_service: CharacterLinkService = Depends(get_link_service),
):
    try:
        result = link_service.link_parent(character_id, payload.parent_character_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CharacterLinkResponse(**result.__dict__)


@router.delete("/characters/{character_id}/link", response_model=CharacterUnlinkResponse)
def unlink_character_from_parent(
    character_id: int,
    link_service: CharacterLinkService = Depends(get_link_service),
):
    try:
        result = link_service.unlink_parent(character_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CharacterUnlinkResponse(**result.__dict__)


@router.post("/list/start", response_model=CatalogJobResponse)
def start_catalog_list(payload: CatalogListStartRequest):
    _require_danbooru()
    job = character_catalog_job_manager.start_catalog_list(
        min_post_count=payload.min_post_count,
        restart=payload.restart,
        only_new=payload.only_new,
    )
    return CatalogJobResponse.from_state(job)


@router.post("/tags/start", response_model=CatalogJobResponse)
def start_catalog_tags(payload: CatalogTagsStartRequest, db: Session = Depends(get_db)):
    _require_danbooru()
    unique_ids = list(dict.fromkeys(payload.character_ids))
    found = db.query(GlobalCharacter.id).filter(GlobalCharacter.id.in_(unique_ids)).count()
    if found != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more characters not found")
    job = character_catalog_job_manager.start_catalog_tags(unique_ids)
    return CatalogJobResponse.from_state(job)


@router.post("/tags/retry-failed", response_model=CatalogJobResponse)
def retry_failed_catalog_tags(
    payload: CatalogRetryFailedRequest,
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    _require_danbooru()
    ids = service.list_failed_ids(limit=payload.limit)
    if not ids:
        raise HTTPException(status_code=404, detail="No failed or partial characters to retry")
    job = character_catalog_job_manager.start_catalog_tags(ids)
    return CatalogJobResponse.from_state(job)


@router.post("/tags/collect-all", response_model=CatalogJobListResponse)
def collect_all_uncollected_catalog_tags(
    payload: CatalogCollectAllRequest,
    service: CharacterCatalogService = Depends(get_catalog_service),
):
    """미수집(collect_status != completed) 캐릭터 전체를 post_count desc, id asc 순으로 모아
    chunk_size(기본 5000)개씩 나눠 각각 하나의 통합 태그 수집 job으로 작업 목록에 올린다."""
    _require_danbooru()
    ids = service.list_uncollected_ids(limit=payload.limit)
    if not ids:
        raise HTTPException(status_code=404, detail="No uncollected characters remaining")
    chunk_size = payload.chunk_size
    chunks = [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]
    jobs = [character_catalog_job_manager.start_catalog_tags(chunk) for chunk in chunks]
    return CatalogJobListResponse(items=[CatalogJobResponse.from_state(job) for job in jobs])


@router.get("/jobs", response_model=CatalogJobListResponse)
def list_catalog_jobs():
    jobs = character_catalog_job_manager.list_visible_jobs()
    return CatalogJobListResponse(items=[CatalogJobResponse.from_state(job) for job in jobs])


@router.get("/jobs/{job_id}", response_model=CatalogJobResponse)
def get_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/pause", response_model=CatalogJobResponse)
def pause_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=400, detail="Only running jobs can be paused")
    character_catalog_job_manager.pause_job(job_id)
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/resume", response_model=CatalogJobResponse)
def resume_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=400, detail="Only paused jobs can be resumed")
    character_catalog_job_manager.resume_job(job_id)
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)


@router.post("/jobs/{job_id}/cancel", response_model=CatalogJobResponse)
def cancel_catalog_job(job_id: str):
    job = character_catalog_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "cancelled":
        return CatalogJobResponse.from_state(job)
    if job.status not in {"queued", "paused"}:
        raise HTTPException(status_code=400, detail="Only queued or paused jobs can be cancelled")
    if not character_catalog_job_manager.cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job could not be cancelled")
    job = character_catalog_job_manager.get_job(job_id)
    return CatalogJobResponse.from_state(job)
