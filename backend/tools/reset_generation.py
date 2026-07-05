from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.models.generation_job import GenerationJob  # noqa: E402
from app.models.global_character import GlobalCharacter  # noqa: E402
from app.models.global_character_generation_job import GlobalCharacterGenerationJob  # noqa: E402
from app.models.global_character_image import GlobalCharacterImage  # noqa: E402
from app.models.global_character_review import GlobalCharacterReview  # noqa: E402
from app.models.image import Image  # noqa: E402
from app.models.review import Review  # noqa: E402
from app.models.series import Series  # noqa: E402


def _clear_generated_image_files() -> dict[str, int]:
    pending_dir = settings.output_dir / "generated_images" / "pending_review"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_removed = 0
    for path in pending_dir.iterdir():
        if path.is_file():
            path.unlink()
            pending_removed += 1

    thumbs_dir = settings.output_dir / "generated_images" / "thumbs"
    thumbs_removed = 0
    if thumbs_dir.exists():
        for path in thumbs_dir.rglob("*"):
            if path.is_file():
                path.unlink()
                thumbs_removed += 1

    return {
        "pending_review_files_removed": pending_removed,
        "thumbnail_files_removed": thumbs_removed,
    }


def reset_generation() -> dict[str, int | str]:
    init_db()
    db = SessionLocal()
    try:
        deleted = {
            "reviews": db.query(Review).delete(synchronize_session=False),
            "images": db.query(Image).delete(synchronize_session=False),
            "generation_jobs": db.query(GenerationJob).delete(synchronize_session=False),
            "global_character_reviews": db.query(GlobalCharacterReview).delete(synchronize_session=False),
            "global_character_images": db.query(GlobalCharacterImage).delete(synchronize_session=False),
            "global_character_generation_jobs": db.query(GlobalCharacterGenerationJob).delete(
                synchronize_session=False
            ),
        }
        db.commit()

        characters_reset = (
            db.query(Character)
            .filter(Character.status == "generated")
            .update({Character.status: "confirmed"}, synchronize_session=False)
        )
        series_reset = (
            db.query(Series)
            .filter(Series.status.in_(["generated", "generating"]))
            .update({Series.status: "tagged"}, synchronize_session=False)
        )
        db.commit()

        file_stats = _clear_generated_image_files()

        return {
            **deleted,
            "characters_status_reset": characters_reset,
            "series_status_reset": series_reset,
            **file_stats,
            "characters_total": db.query(Character).count(),
            "global_characters_total": db.query(GlobalCharacter).count(),
            "remaining_global_images": db.query(GlobalCharacterImage).count(),
        }
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Delete generated images and reset generation-related DB rows so image "
            "generation can start from scratch. Characters and global characters are kept."
        ),
    )


def main() -> int:
    build_parser().parse_args()
    try:
        result = reset_generation()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    print("[DONE] Generation data reset complete.")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("[INFO] Restart the app before starting a new generation batch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
