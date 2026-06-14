from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.integrations.danbooru.client import DanbooruAuthError, DanbooruClient  # noqa: E402
from app.integrations.danbooru.series_collector import SeriesTagCollector  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Danbooru copyright tags into input/series.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.input_dir / "series.csv",
        help="Output CSV path (default: input/series.csv)",
    )
    parser.add_argument(
        "--max-tags",
        type=int,
        default=None,
        help="Maximum number of series tags to collect (default: all available)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum API pages to fetch (1000 tags per page)",
    )
    parser.add_argument(
        "--min-post-count",
        type=int,
        default=1,
        help="Skip tags below this post_count",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start page for Danbooru tag search",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify Danbooru credentials",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not settings.danbooru_configured:
        print("[ERROR] Danbooru credentials are not configured.")
        print()
        print("1) Copy input/danbooru.env.example to input/danbooru.env")
        print("2) Fill in username and api_key")
        print("   or put username + api_key in input/danbooru_api_key.txt (2 lines)")
        print()
        print("API key location: https://danbooru.donmai.us/profile")
        return 1

    try:
        client = DanbooruClient()
        profile = client.verify_credentials()
        print(
            f"[OK] Danbooru credentials verified for '{profile.get('username')}' "
            f"(sample tag: {profile.get('sample_tag')})"
        )

        if args.verify_only:
            return 0

        collector = SeriesTagCollector(client)
        print("[INFO] Collecting copyright tags (category=3, hide_empty=yes, order=count)...")
        rows = collector.collect(
            max_tags=args.max_tags,
            max_pages=args.max_pages,
            min_post_count=args.min_post_count,
            start_page=args.start_page,
        )

        if not rows:
            print("[WARN] No tags collected.")
            return 1

        output_path: Path = args.output
        if output_path.exists():
            backup_path = output_path.with_suffix(f".bak_{output_path.stat().st_mtime_ns}.csv")
            output_path.replace(backup_path)
            print(f"[INFO] Backed up existing file to {backup_path.name}")

        collector.write_csv(rows, output_path)
        print(f"[DONE] Wrote {len(rows)} series tags to {output_path}")
        if rows:
            top = rows[0]
            bottom = rows[-1]
            print(f"       Top: {top.series_tag} ({top.post_count:,})")
            print(f"       Bottom: {bottom.series_tag} ({bottom.post_count:,})")
        return 0
    except DanbooruAuthError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
