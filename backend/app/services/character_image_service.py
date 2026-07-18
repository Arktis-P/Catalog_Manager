from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.image import Image
from app.services.identity_checker import IDENTITY_CHECKER_VERSION, check_identity
from app.services.prompt_service import v2_multicolor_prompt_candidates
from app.services.quality_checker import QUALITY_CHECKER_VERSION, check_quality

CATALOG_SELECTED_DIR_NAME = "catalog_selected"

# quality_status/identity_status 우선순위 (임시 대표 등록 판정에 사용, §10)
_STATUS_RANK = {"reject": 0, "warning": 1, "pass": 2}


def _catalog_selected_dir() -> Path:
    path = settings.output_dir / "generated_images" / CATALOG_SELECTED_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def move_image_to_catalog_folder(db: Session, image: Image | GlobalCharacterImage) -> None:
    """리뷰에서 커버로 선택된 이미지를 별도의 catalog_selected 폴더로 물리적으로
    이동한다. 이미 그 폴더에 있으면(재선택 등) 아무 것도 하지 않는다."""
    current_path = settings.project_root / image.image_path
    if CATALOG_SELECTED_DIR_NAME in current_path.parts:
        return
    if not current_path.is_file():
        return

    dest_dir = _catalog_selected_dir()
    dest_path = dest_dir / current_path.name
    if dest_path.exists():
        dest_path = dest_dir / f"{current_path.stem}_{image.id}{current_path.suffix}"

    shutil.move(str(current_path), str(dest_path))
    image.image_path = dest_path.relative_to(settings.project_root).as_posix()
    db.flush()


def purge_noncover_images(db: Session, character: Character) -> int:
    """커버로 선택되지 않은 이미지를 파일+DB 모두 삭제한다. 사용자가 명시적으로
    버튼을 눌렀을 때만 호출되는 되돌릴 수 없는 동작이므로 자동 호출 금지."""
    images = db.query(Image).filter(Image.character_id == character.id, Image.is_cover.is_(False)).all()
    removed = 0
    for image in images:
        file_path = settings.project_root / image.image_path
        if file_path.is_file():
            file_path.unlink()
        db.delete(image)
        if image in character.images:
            character.images.remove(image)
        removed += 1
    if removed:
        db.flush()
    return removed


def purge_noncover_images_global(db: Session, character: GlobalCharacter) -> int:
    """커버로 선택되지 않은 이미지를 파일+DB 모두 삭제한다(GlobalCharacter 버전)."""
    images = (
        db.query(GlobalCharacterImage)
        .filter(GlobalCharacterImage.global_character_id == character.id, GlobalCharacterImage.is_cover.is_(False))
        .all()
    )
    removed = 0
    for image in images:
        file_path = settings.project_root / image.image_path
        if file_path.is_file():
            file_path.unlink()
        db.delete(image)
        if image in character.images:
            character.images.remove(image)
        removed += 1
    if removed:
        db.flush()
    return removed


def purge_global_character_images(db: Session, character: GlobalCharacter) -> int:
    images = db.query(GlobalCharacterImage).filter(GlobalCharacterImage.global_character_id == character.id).all()
    removed = 0
    for image in images:
        file_path = settings.project_root / image.image_path
        if file_path.is_file():
            file_path.unlink()
        db.delete(image)
        removed += 1

    review = character.review
    if review:
        review.cover_image_id = None

    for image in list(character.images):
        if image in character.images:
            character.images.remove(image)

    if removed:
        db.flush()
    return removed


# ── V2 자동 검사 파이프라인 연결 (WP4) ─────────────────────────────────
# quality/identity 검사 실행과 결과 저장까지만 담당한다. 재생성 트리거·Job
# 관리는 이 함수의 책임이 아니다 (WP5가 검사 결과를 소비한다).


def is_provisional_eligible(quality_status: str | None, identity_status: str | None) -> bool:
    """quality_status >= warning AND identity_status >= warning 인지 판정한다 (§10)."""
    quality_rank = _STATUS_RANK.get(quality_status or "")
    identity_rank = _STATUS_RANK.get(identity_status or "")
    if quality_rank is None or identity_rank is None:
        return False
    return quality_rank >= _STATUS_RANK["warning"] and identity_rank >= _STATUS_RANK["warning"]


def apply_provisional_status(
    db: Session, image: GlobalCharacterImage, character: GlobalCharacter
) -> None:
    """조건을 만족하면 image를 캐릭터의 임시 대표 이미지로 등록한다.

    기존 provisional 이미지는 해제되며, 캐릭터당 1장만 유지된다.
    """
    if not is_provisional_eligible(image.quality_status, image.identity_status):
        image.is_provisional = False
        return

    (
        db.query(GlobalCharacterImage)
        .filter(
            GlobalCharacterImage.global_character_id == character.id,
            GlobalCharacterImage.id != image.id,
            GlobalCharacterImage.is_provisional.is_(True),
        )
        .update({"is_provisional": False})
    )
    image.is_provisional = True


def run_v2_quality_identity_checks(
    db: Session,
    image: GlobalCharacterImage,
    character: GlobalCharacter,
    *,
    hf_token: str | None = None,
    hf_wd_model: str | None = None,
) -> GlobalCharacterImage:
    """V2 생성 이미지 저장 파이프라인: quality 검사 → (warning 이상이면) identity
    검사 → 결과 저장 → 임시 대표 등록 판정까지 수행한다 (§3, §10)."""
    image_path = settings.project_root / image.image_path
    quality = check_quality(image_path)

    now = datetime.now()
    image.quality_status = quality.status
    image.quality_score = quality.score
    image.quality_reasons = json.dumps(quality.reasons, ensure_ascii=False)
    image.quality_checked_at = now
    image.quality_checker_version = QUALITY_CHECKER_VERSION

    if quality.status != "reject":
        expected_multicolor_tags = v2_multicolor_prompt_candidates(db, character.id)

        identity = check_identity(
            image_path,
            character_tag=character.character_tag,
            primary_hair_color=character.primary_hair_color,
            expected_multicolor_tags=expected_multicolor_tags,
            gender=character.gender,
            hf_token=hf_token,
            hf_wd_model=hf_wd_model,
        )
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

    apply_provisional_status(db, image, character)
    db.flush()
    return image


def purge_character_images(db: Session, character: Character) -> int:
    images = db.query(Image).filter(Image.character_id == character.id).all()
    removed = 0
    for image in images:
        file_path = settings.project_root / image.image_path
        if file_path.is_file():
            file_path.unlink()
        db.delete(image)
        removed += 1

    review = character.review
    if review:
        review.cover_image_id = None

    for image in list(character.images):
        if image in character.images:
            character.images.remove(image)

    if removed:
        db.flush()
    return removed
