from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401 - register SQLAlchemy relationships
from app.database import SessionLocal, init_db
from app.services.character_group_service import (
    GROUP_RECALCULATE_ALL_BATCH_SIZE,
    CharacterGroupService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recalculate character parent/child grouping suggestions for every "
            "eligible parent-anchor GlobalCharacter. Rejected pairs are always "
            "preserved. Full --apply runs (no --character-tag) use the same "
            "keyset-batched recalculation (CharacterGroupService."
            "recalculate_all_batched) as the request-time recalculate-all "
            "endpoint, so this script is a maintenance convenience wrapper "
            "rather than the only safe place to trigger a full recalculation."
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
    parser.add_argument(
        "--batch-size",
        type=int,
        default=GROUP_RECALCULATE_ALL_BATCH_SIZE,
        help=(
            "Anchors per keyset batch for full --apply runs (no --character-tag); "
            f"ignored otherwise (default: {GROUP_RECALCULATE_ALL_BATCH_SIZE})"
        ),
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
        service = CharacterGroupService(db)
        if args.character_tag:
            # Targeted single-group recalculation keeps using recalculate_all's
            # character_tag filter, which honors dry-run via apply=False.
            summary = service.recalculate_all(
                character_tag=args.character_tag,
                apply=args.apply,
                limit_per_anchor=args.limit_per_anchor,
            )
        elif args.apply:
            # Full apply runs use the keyset-batched method - the same code
            # path the request-time recalculate-all endpoint uses - so a
            # catalogue-wide recalculation never materializes every anchor
            # into memory at once.
            summary = service.recalculate_all_batched(
                limit_per_anchor=args.limit_per_anchor,
                batch_size=args.batch_size,
            )
        else:
            # recalculate_all_batched has no dry-run mode (it commits every
            # batch unconditionally), so a full dry-run preview still goes
            # through recalculate_all(apply=False), which rolls back instead
            # of committing.
            summary = service.recalculate_all(
                apply=False,
                limit_per_anchor=args.limit_per_anchor,
            )
        print_summary(summary, apply=args.apply)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
