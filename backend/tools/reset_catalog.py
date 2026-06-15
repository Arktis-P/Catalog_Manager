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
from app.models.image import Image  # noqa: E402
from app.models.review import Review  # noqa: E402
from app.models.series import Series  # noqa: E402
from app.services.series_service import SeriesService  # noqa: E402


def _clear_pending_review_images() -> int:
    pending_dir = settings.output_dir / "generated_images" / "pending_review"
    pending_dir.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in pending_dir.iterdir():
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def _reset_series_collect_state(db) -> int:
    rows = db.query(Series).all()
    for series in rows:
        series.last_collect_created = 0
        series.last_collect_skipped = 0
        series.last_appearance_updated = 0
        series.parent_series_id = None
        series.merged_moved_count = 0
        series.merged_duplicate_count = 0
        if series.status in {"collected", "tagged", "collecting", "disabled", "all_collected"}:
            series.status = "pending"
    db.commit()
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset catalogue DB: wipe characters and related data, reload series from series.csv",
    )
    parser.add_argument(
        "--skip-series-import",
        action="store_true",
        help="Only clear characters/reviews/images/jobs; keep existing series rows",
    )
    return parser


def reset_catalog(*, reimport_series: bool = True) -> dict[str, int | str]:
    init_db()
    db = SessionLocal()
    try:
        deleted = {
            "reviews": db.query(Review).delete(),
            "images": db.query(Image).delete(),
            "generation_jobs": db.query(GenerationJob).delete(),
            "characters": db.query(Character).delete(),
        }
        db.commit()
        pending_files_removed = _clear_pending_review_images()

        series_result = {"created": 0, "updated": 0, "merged_duplicates": 0}
        if reimport_series:
            csv_path = settings.input_dir / "series.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"Missing series CSV: {csv_path}")
            series_result = SeriesService(db).import_from_file(csv_path, replace=True)
        else:
            series_reset = _reset_series_collect_state(db)

        return {
            **deleted,
            "pending_review_files_removed": pending_files_removed,
            "series_created": series_result["created"],
            "series_updated": series_result["updated"],
            "series_merged_duplicates": series_result.get("merged_duplicates", 0),
            "series_total": db.query(Series).count(),
            "characters_total": db.query(Character).count(),
            **({"series_reset": series_reset} if not reimport_series else {}),
        }
    finally:
        db.close()


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = reset_catalog(reimport_series=not args.skip_series_import)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    print("[DONE] Catalogue DB reset complete.")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("[INFO] Restart the app before collecting characters again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
