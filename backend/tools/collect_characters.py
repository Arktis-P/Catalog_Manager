from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.integrations.danbooru.client import DanbooruAuthError  # noqa: E402
from app.services.character_service import CharacterService  # noqa: E402
from app.services.series_service import SeriesService  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Danbooru character tags for series in the DB")
    parser.add_argument("--series-tag", type=str, default=None, help="Collect for one series tag")
    parser.add_argument("--series-id", type=int, default=None, help="Collect for one series id")
    parser.add_argument("--status", type=str, default="pending", help="Batch status filter")
    parser.add_argument("--limit", type=int, default=1, help="Number of series to process in batch mode")
    parser.add_argument("--import-csv", action="store_true", help="Import input/series.csv before collecting")
    parser.add_argument("--replace-csv", action="store_true", help="Replace existing series rows when importing CSV")
    parser.add_argument("--max-characters", type=int, default=None, help="Limit new characters counted per series")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not settings.danbooru_configured:
        print("[ERROR] Configure Danbooru credentials in input/danbooru.env first.")
        return 1

    init_db()
    db = SessionLocal()
    try:
        if args.import_csv:
            csv_path = settings.input_dir / "series.csv"
            if not csv_path.exists():
                print(f"[ERROR] Missing CSV: {csv_path}")
                return 1
            result = SeriesService(db).import_from_file(csv_path, replace=args.replace_csv)
            print(f"[INFO] Imported series CSV: created={result['created']} updated={result['updated']}")

        service = CharacterService(db)
        if args.series_tag:
            result = service.collect_for_series_tag(args.series_tag, max_characters=args.max_characters)
            print(
                f"[DONE] {result.series_tag}: discovered={result.discovered} "
                f"created={result.created} skipped={result.skipped_existing}"
            )
            return 0

        if args.series_id:
            from app.models.series import Series

            series = db.query(Series).filter(Series.id == args.series_id).first()
            if not series:
                print(f"[ERROR] Series id not found: {args.series_id}")
                return 1
            result = service.collect_for_series(series, max_characters=args.max_characters)
            print(
                f"[DONE] {result.series_tag}: discovered={result.discovered} "
                f"created={result.created} skipped={result.skipped_existing}"
            )
            return 0

        summary = service.collect_batch(status=args.status, limit=args.limit)
        print(
            f"[DONE] series_processed={summary.series_processed} "
            f"discovered={summary.total_discovered} created={summary.total_created} "
            f"skipped={summary.total_skipped_existing}"
        )
        for item in summary.results:
            print(
                f"  - {item.series_tag}: discovered={item.discovered} "
                f"created={item.created} skipped={item.skipped_existing}"
            )
        return 0
    except DanbooruAuthError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
