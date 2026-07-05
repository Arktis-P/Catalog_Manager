from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models.character import Character
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.image import Image


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
