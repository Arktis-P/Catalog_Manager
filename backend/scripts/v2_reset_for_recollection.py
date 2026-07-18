from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401 - register SQLAlchemy relationships
from app.config import settings
from app.database import SessionLocal, init_db
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from sqlalchemy.orm import Session


BATCH_LOG_SIZE = 1000
IMAGE_SUBDIRS = (
    Path("output/generated_images/pending_review"),
    Path("output/generated_images/catalog_selected"),
    Path("output/generated_images/thumbs"),
)


@dataclass
class ResetSummary:
    dry_run: bool
    scope: str
    character_count: int = 0
    image_rows: int = 0
    review_rows: int = 0
    relevance_rows: int = 0
    files: int = 0
    bytes: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reset V2 image and appearance collection state.")
    parser.add_argument("--apply", action="store_true", help="Apply deletes and database changes")
    parser.add_argument(
        "--scope",
        choices=("images", "appearance", "all"),
        default="all",
        help="Reset scope (default: all)",
    )
    parser.add_argument("--character-tag", help="Limit reset to one GlobalCharacter.character_tag")
    return parser


def _target_query(db: Session, character_tag: str | None):
    query = db.query(GlobalCharacter)
    if character_tag:
        query = query.filter(GlobalCharacter.character_tag == character_tag)
    return query


def _target_ids(db: Session, character_tag: str | None) -> list[int] | None:
    # None이면 전체 대상: SQLite의 IN 절 변수 한도(기본 999개) 때문에 대량 id를
    # IN으로 넘기지 않고 필터 자체를 생략한다.
    if character_tag is None:
        return None
    return [row.id for row in _target_query(db, character_tag).order_by(GlobalCharacter.id).all()]


def _filter_by_character_ids(query, column, target_ids: list[int] | None):
    if target_ids is None:
        return query
    return query.filter(column.in_(target_ids))


def _existing_file_info(paths: list[Path]) -> tuple[int, int]:
    count = 0
    size = 0
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        count += 1
        size += path.stat().st_size
    return count, size


def _image_paths_for_values(project_root: Path, values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        image_path = Path(value)
        paths.append(image_path if image_path.is_absolute() else project_root / image_path)
    return paths


def _orphan_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative_dir in IMAGE_SUBDIRS:
        directory = project_root / relative_dir
        if not directory.exists():
            continue
        paths.extend(path for path in directory.rglob("*") if path.is_file())
    return paths


def _unlink_files(paths: list[Path]) -> tuple[int, int]:
    count = 0
    size = 0
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        file_size = path.stat().st_size
        path.unlink()
        count += 1
        size += file_size
        if count % BATCH_LOG_SIZE == 0:
            print(f"  deleted files: {count}")
    return count, size


def _recalculate_collect_status(character: GlobalCharacter) -> None:
    # There is no shared helper in the collection service. The collection flow derives
    # collect_status from appearance/gender/series sub-statuses; after resetting
    # appearance, keep completed only impossible, partial if another sub-status remains done.
    if (
        character.appearance_status == "completed"
        and character.gender_status == "completed"
        and character.series_status == "completed"
    ):
        character.collect_status = "completed"
    elif character.gender_status == "completed" or character.series_status == "completed":
        character.collect_status = "partial"
    else:
        character.collect_status = "uncollected"


def _reset_images(
    db: Session,
    *,
    project_root: Path,
    character_tag: str | None,
    apply: bool,
    summary: ResetSummary,
) -> None:
    target_ids = _target_ids(db, character_tag)
    if target_ids is not None and not target_ids:
        return

    path_query = _filter_by_character_ids(
        db.query(GlobalCharacterImage.image_path),
        GlobalCharacterImage.global_character_id,
        target_ids,
    )
    row_paths = _image_paths_for_values(project_root, [row[0] for row in path_query])
    file_paths = list(row_paths)
    if character_tag is None:
        file_paths.extend(_orphan_paths(project_root))
    summary.image_rows = len(row_paths)
    summary.files, summary.bytes = _existing_file_info(file_paths)

    review_query = _filter_by_character_ids(
        db.query(GlobalCharacterReview), GlobalCharacterReview.global_character_id, target_ids
    )
    summary.review_rows = review_query.count()
    summary.character_count = _target_query(db, character_tag).count()

    if not apply:
        return

    _unlink_files(file_paths)

    for review in review_query.order_by(GlobalCharacterReview.id).yield_per(BATCH_LOG_SIZE):
        review.cover_image_id = None
        review.review_status = "pending"
        review.final_prompt = None
        review.selected_tags = None
    db.flush()

    for index, character in enumerate(
        _target_query(db, character_tag).order_by(GlobalCharacter.id).yield_per(BATCH_LOG_SIZE),
        start=1,
    ):
        character.generation_status = "not_generated"
        character.generation_attempts = 0
        character.total_generation_attempts = 0
        character.prompt_variant_attempts = None
        character.last_failure_reason = None
        character.prompt_revision_reason = None
        character.prompt_revision_level = None
        character.error_message = None
        if index % BATCH_LOG_SIZE == 0:
            print(f"  reset image state for characters: {index}")

    _filter_by_character_ids(
        db.query(GlobalCharacterImage), GlobalCharacterImage.global_character_id, target_ids
    ).delete(synchronize_session=False)


def _reset_appearance(db: Session, *, character_tag: str | None, apply: bool, summary: ResetSummary) -> None:
    target_ids = _target_ids(db, character_tag)
    if target_ids is not None and not target_ids:
        return

    relevance_query = _filter_by_character_ids(
        db.query(CharacterAppearanceTagRelevance),
        CharacterAppearanceTagRelevance.global_character_id,
        target_ids,
    )
    summary.relevance_rows = relevance_query.count()
    summary.character_count = max(summary.character_count, _target_query(db, character_tag).count())

    if not apply:
        return

    relevance_query.delete(synchronize_session=False)
    for index, character in enumerate(
        _target_query(db, character_tag).order_by(GlobalCharacter.id).yield_per(BATCH_LOG_SIZE),
        start=1,
    ):
        character.hair_color = None
        character.hair_shape = None
        character.multi_color_hair = None
        character.eye_color = None
        character.feature_tags = None
        character.primary_hair_color = None
        character.primary_hair_needs_review = False
        character.base_prompt = None
        character.previous_base_prompt = None
        character.appearance_status = "uncollected"
        _recalculate_collect_status(character)
        if index % BATCH_LOG_SIZE == 0:
            print(f"  reset appearance state for characters: {index}")


def reset_for_recollection(
    db: Session,
    *,
    project_root: Path,
    apply: bool = False,
    scope: str = "all",
    character_tag: str | None = None,
) -> ResetSummary:
    summary = ResetSummary(dry_run=not apply, scope=scope)
    if scope in {"images", "all"}:
        _reset_images(db, project_root=project_root, character_tag=character_tag, apply=apply, summary=summary)
    if scope in {"appearance", "all"}:
        _reset_appearance(db, character_tag=character_tag, apply=apply, summary=summary)

    if apply:
        db.commit()
    else:
        db.rollback()
    return summary


def print_summary(summary: ResetSummary) -> None:
    mode = "dry-run" if summary.dry_run else "apply"
    print(f"Mode: {mode}")
    print(f"Scope: {summary.scope}")
    print(f"Characters: {summary.character_count}")
    print(f"Image rows: {summary.image_rows}")
    print(f"Review rows reset: {summary.review_rows}")
    print(f"Relevance rows: {summary.relevance_rows}")
    print(f"Files: {summary.files}")
    print(f"Bytes: {summary.bytes}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    init_db()
    db = SessionLocal()
    try:
        summary = reset_for_recollection(
            db,
            project_root=settings.project_root,
            apply=args.apply,
            scope=args.scope,
            character_tag=args.character_tag,
        )
        print_summary(summary)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
