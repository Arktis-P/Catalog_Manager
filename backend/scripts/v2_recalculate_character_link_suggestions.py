from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401 - register SQLAlchemy relationships
from app.database import SessionLocal, init_db
from app.services.character_group_service import CharacterGroupService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recalculate character parent/child grouping suggestions for every "
            "eligible parent-anchor GlobalCharacter. Rejected pairs are always "
            "preserved; this is the only place a full (all-anchor) recalculation "
            "should run, since it is too expensive for a request-time endpoint."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument(
        "--character-tag",
        help="Limit recalculation to the group anchored at this GlobalCharacter.character_tag",
    )
    parser.add_argument(
        "--limit-per-anchor",
        type=int,
        default=30,
        help="Max candidates considered per anchor (default: 30)",
    )
    return parser


def print_summary(summary, *, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print(f"Mode: {mode}")
    print(f"Scanned anchors: {summary.scanned_anchors}")
    print(f"Pending suggestions: {summary.pending_total}")
    print(f"Accepted suggestions: {summary.accepted_total}")
    print(f"Rejected suggestions (preserved): {summary.rejected_total}")
    print(f"Superseded suggestions: {summary.superseded_total}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    db = SessionLocal()
    try:
        summary = CharacterGroupService(db).recalculate_all(
            character_tag=args.character_tag,
            apply=args.apply,
            limit_per_anchor=args.limit_per_anchor,
        )
        print_summary(summary, apply=args.apply)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
