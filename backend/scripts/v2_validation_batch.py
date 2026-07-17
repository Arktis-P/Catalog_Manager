from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.series import Series
from app.services.db_write_queue import commit_db_session
from app.services.prompt_service import refresh_global_character_base_prompt
from app.services.tag_relevance_service import TagRelevanceService
from app.services.v2_generation_pipeline import V2GenerationPipeline


PROCESSED_GENERATION_STATUSES = {"generated", "generation_failed", "likely_untrained"}


@dataclass(frozen=True)
class CharacterPlan:
    id: int
    character_tag: str
    post_count: int
    generation_status: str
    has_relevance: bool
    has_base_prompt: bool
    has_checked_image: bool


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the V2 validation batch for top global characters.")
    parser.add_argument("--limit", type=int, default=500, help="Number of characters to select (default: 500)")
    parser.add_argument("--offset", type=int, default=0, help="Offset within the post_count ordered target list")
    parser.add_argument("--start", type=int, default=None, help="1-based inclusive rank start")
    parser.add_argument("--end", type=int, default=None, help="1-based inclusive rank end")
    parser.add_argument("--series", help="Limit targets to a series_tag or display_name")
    parser.add_argument("--dry-run", action="store_true", help="Print target and phase plan without API calls or writes")
    parser.add_argument("--skip-relevance", action="store_true", help="Skip appearance relevance collection")
    parser.add_argument("--skip-prompt", action="store_true", help="Skip base prompt refresh")
    parser.add_argument("--skip-generation", action="store_true", help="Skip V2 generation pipeline")
    return parser


def _range_values(args: argparse.Namespace) -> tuple[int, int]:
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            raise SystemExit("--start and --end must be provided together")
        if args.start < 1 or args.end < args.start:
            raise SystemExit("--start/--end must describe a valid 1-based inclusive range")
        return args.start - 1, args.end - args.start + 1
    if args.offset < 0 or args.limit < 1:
        raise SystemExit("--offset must be >= 0 and --limit must be >= 1")
    return args.offset, args.limit


def select_targets(db: Session, *, limit: int, offset: int = 0, series: str | None = None) -> list[GlobalCharacter]:
    query = db.query(GlobalCharacter)
    if series:
        query = (
            query.join(CharacterSeriesLink, CharacterSeriesLink.global_character_id == GlobalCharacter.id)
            .join(Series, Series.id == CharacterSeriesLink.series_id)
            .filter((Series.series_tag == series) | (Series.display_name == series))
        )
    return (
        query.order_by(GlobalCharacter.post_count.desc(), GlobalCharacter.character_tag.asc(), GlobalCharacter.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _has_relevance(db: Session, character_id: int) -> bool:
    return db.scalar(
        select(
            exists().where(CharacterAppearanceTagRelevance.global_character_id == character_id)
        )
    )


def _has_checked_image(db: Session, character_id: int) -> bool:
    return db.scalar(
        select(
            exists().where(
                GlobalCharacterImage.global_character_id == character_id,
                GlobalCharacterImage.is_rejected.is_(False),
                GlobalCharacterImage.quality_status.is_not(None),
            )
        )
    )


def build_plan(db: Session, characters: list[GlobalCharacter]) -> list[CharacterPlan]:
    return [
        CharacterPlan(
            id=character.id,
            character_tag=character.character_tag,
            post_count=character.post_count,
            generation_status=character.generation_status,
            has_relevance=bool(_has_relevance(db, character.id)),
            has_base_prompt=bool(character.base_prompt),
            has_checked_image=bool(_has_checked_image(db, character.id)),
        )
        for character in characters
    ]


def _generation_processed(plan: CharacterPlan) -> bool:
    return plan.generation_status in PROCESSED_GENERATION_STATUSES or plan.has_checked_image


def print_plan(
    plans: list[CharacterPlan],
    *,
    skip_relevance: bool,
    skip_prompt: bool,
    skip_generation: bool,
) -> None:
    print(f"Targets: {len(plans)}")
    print("rank\tid\tpost_count\ttag\trelevance\tprompt\tgeneration")
    for rank, plan in enumerate(plans, start=1):
        relevance = "skip(option)" if skip_relevance else ("skip(done)" if plan.has_relevance else "run")
        prompt = "skip(option)" if skip_prompt else ("skip(done)" if plan.has_base_prompt else "run")
        generation = (
            "skip(option)"
            if skip_generation
            else ("skip(done)" if _generation_processed(plan) else "run")
        )
        print(
            f"{rank}\t{plan.id}\t{plan.post_count}\t{plan.character_tag}\t"
            f"{relevance}\t{prompt}\t{generation}"
        )


def run_batch(args: argparse.Namespace) -> int:
    if not args.dry_run:
        init_db()
    offset, limit = _range_values(args)
    db = SessionLocal()
    try:
        characters = select_targets(db, limit=limit, offset=offset, series=args.series)
        plans = build_plan(db, characters)
        print_plan(
            plans,
            skip_relevance=args.skip_relevance,
            skip_prompt=args.skip_prompt,
            skip_generation=args.skip_generation,
        )
        if args.dry_run:
            print("Dry-run complete: no API calls or database writes were performed.")
            return 0

        summary = {
            "relevance_success": 0,
            "relevance_failed": 0,
            "relevance_skipped": 0,
            "prompt_success": 0,
            "prompt_failed": 0,
            "prompt_skipped": 0,
            "generation_success": 0,
            "generation_failed": 0,
            "generation_skipped": 0,
        }
        relevance_service = TagRelevanceService(db)
        pipeline = V2GenerationPipeline(db)

        for index, plan in enumerate(plans, start=1):
            character = db.query(GlobalCharacter).filter(GlobalCharacter.id == plan.id).first()
            if character is None:
                continue
            print(f"[{index}/{len(plans)}] {character.character_tag}")

            if args.skip_relevance or plan.has_relevance:
                summary["relevance_skipped"] += 1
            else:
                try:
                    relevance_service.collect_for_character(character)
                    summary["relevance_success"] += 1
                except Exception as exc:
                    db.rollback()
                    summary["relevance_failed"] += 1
                    print(f"  relevance failed: {exc}")

            if args.skip_prompt or character.base_prompt:
                summary["prompt_skipped"] += 1
            else:
                try:
                    refresh_global_character_base_prompt(db, character)
                    commit_db_session(db)
                    summary["prompt_success"] += 1
                except Exception as exc:
                    db.rollback()
                    summary["prompt_failed"] += 1
                    print(f"  prompt failed: {exc}")

            refreshed_plan = build_plan(db, [character])[0]
            if args.skip_generation or _generation_processed(refreshed_plan):
                summary["generation_skipped"] += 1
            else:
                try:
                    result = pipeline.run_character(character.id)
                    if result.generation_status == "generated":
                        summary["generation_success"] += 1
                    else:
                        summary["generation_failed"] += 1
                    print(f"  generation: {result.generation_status} attempts={result.generation_attempts}")
                except Exception as exc:
                    db.rollback()
                    summary["generation_failed"] += 1
                    print(f"  generation failed: {exc}")

        print("Summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
