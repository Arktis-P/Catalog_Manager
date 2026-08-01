from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401 - register SQLAlchemy relationships
from app.database import SessionLocal, init_db
from app.services.non_human_review_service import recalculate_non_human_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recalculate non-human pre-review candidate scores/evidence for existing "
            "GlobalCharacter rows. Confirmed/excluded decisions are always preserved."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--character-tag", help="Limit recalculation to one GlobalCharacter.character_tag")
    return parser


def print_summary(summary, *, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print(f"Mode: {mode}")
    print(f"Scanned: {summary.scanned}")
    print(f"Updated: {summary.updated}")
    print(f"Skipped (confirmed/excluded): {summary.skipped_decided}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    db = SessionLocal()
    try:
        summary = recalculate_non_human_candidates(
            db,
            character_tag=args.character_tag,
            apply=args.apply,
        )
        print_summary(summary, apply=args.apply)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
