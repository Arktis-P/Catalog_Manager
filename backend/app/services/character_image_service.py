from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.image import Image

CATALOG_SELECTED_DIR_NAME = "catalog_selected"


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
