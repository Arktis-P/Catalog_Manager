from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview


DEFAULT_OUTPUT = settings.project_root / "data" / "exports" / "v2_validation_report.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build V2 validation statistics report.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON output path")
    return parser


def _distribution(db: Session, column: Any, *, include_null_as: str | None = None) -> dict[str, int]:
    label = func.coalesce(column, include_null_as) if include_null_as else column
    rows = db.query(label.label("bucket"), func.count()).group_by("bucket").all()
    return {str(bucket): int(count) for bucket, count in rows if bucket is not None}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_report(db: Session) -> dict[str, Any]:
    total_characters = int(db.query(func.count(GlobalCharacter.id)).scalar() or 0)
    total_images = int(db.query(func.count(GlobalCharacterImage.id)).scalar() or 0)
    generation_status = _distribution(db, GlobalCharacter.generation_status, include_null_as="not_generated")
    quality_status = _distribution(db, GlobalCharacterImage.quality_status, include_null_as="unchecked")
    identity_status = _distribution(db, GlobalCharacterImage.identity_status, include_null_as="unchecked")

    quality_reject_by_character = Counter(
        count
        for (count,) in (
            db.query(func.count(GlobalCharacterImage.id))
            .filter(GlobalCharacterImage.quality_status == "reject")
            .group_by(GlobalCharacterImage.global_character_id)
            .all()
        )
    )
    characters_with_quality_reject = sum(quality_reject_by_character.values())
    generated_after_quality_retry = int(
        db.query(func.count(GlobalCharacter.id))
        .filter(
            GlobalCharacter.generation_status == "generated",
            GlobalCharacter.id.in_(
                db.query(GlobalCharacterImage.global_character_id)
                .filter(GlobalCharacterImage.quality_status == "reject")
                .distinct()
            ),
        )
        .scalar()
        or 0
    )

    revision_level_distribution = _distribution(db, GlobalCharacter.prompt_revision_level)
    prompt_revision_success_count = int(
        db.query(func.count(GlobalCharacter.id))
        .filter(GlobalCharacter.prompt_revision_level.is_not(None), GlobalCharacter.generation_status == "generated")
        .scalar()
        or 0
    )

    total_reviewed = int(
        db.query(func.count(GlobalCharacterReview.id))
        .filter(GlobalCharacterReview.review_status == "completed")
        .scalar()
        or 0
    )
    quality_reject_rating_3_plus = int(
        db.query(func.count(GlobalCharacterImage.id))
        .join(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacterImage.global_character_id)
        .filter(
            GlobalCharacterImage.quality_status == "reject",
            GlobalCharacterReview.review_status == "completed",
            GlobalCharacterReview.rating >= 3,
        )
        .scalar()
        or 0
    )
    identity_reject_rating_3_plus = int(
        db.query(func.count(GlobalCharacterImage.id))
        .join(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacterImage.global_character_id)
        .filter(
            GlobalCharacterImage.identity_status == "reject",
            GlobalCharacterReview.review_status == "completed",
            GlobalCharacterReview.rating >= 3,
        )
        .scalar()
        or 0
    )
    warning_or_pass_rating_0 = int(
        db.query(func.count(GlobalCharacterImage.id))
        .join(GlobalCharacterReview, GlobalCharacterReview.global_character_id == GlobalCharacterImage.global_character_id)
        .filter(
            GlobalCharacterImage.quality_status.in_(("pass", "warning")),
            GlobalCharacterImage.identity_status.in_(("pass", "warning")),
            GlobalCharacterReview.review_status == "completed",
            GlobalCharacterReview.rating == 0,
        )
        .scalar()
        or 0
    )

    multicolor_suggestion_images = 0
    for (raw,) in db.query(GlobalCharacterImage.suggested_multicolor_tags).all():
        if _json_list(raw):
            multicolor_suggestion_images += 1

    primary_hair_review_count = int(
        db.query(func.count(GlobalCharacter.id))
        .filter(GlobalCharacter.primary_hair_needs_review.is_(True))
        .scalar()
        or 0
    )

    generation_failed = generation_status.get("generation_failed", 0)
    likely_untrained = generation_status.get("likely_untrained", 0)

    return {
        "totals": {
            "characters": total_characters,
            "images": total_images,
            "completed_reviews": total_reviewed,
        },
        "quality_status_distribution": quality_status,
        "identity_status_distribution": identity_status,
        "generation_status_distribution": generation_status,
        "generation_status_ratios": {
            "generation_failed": _ratio(generation_failed, total_characters),
            "likely_untrained": _ratio(likely_untrained, total_characters),
        },
        "auto_regeneration": {
            "quality_reject_count_distribution_per_character": {
                str(key): value for key, value in sorted(quality_reject_by_character.items())
            },
            "characters_with_quality_reject": characters_with_quality_reject,
            "generated_after_quality_retry": generated_after_quality_retry,
            "quality_retry_success_rate": _ratio(generated_after_quality_retry, characters_with_quality_reject),
            "identity_prompt_revision_level_distribution": revision_level_distribution,
            "prompt_revision_success_count": prompt_revision_success_count,
        },
        "prompt_revision": {
            "success_count": prompt_revision_success_count,
            "level_distribution": revision_level_distribution,
        },
        "appearance_flags": {
            "primary_hair_needs_review_count": primary_hair_review_count,
            "primary_hair_needs_review_ratio": _ratio(primary_hair_review_count, total_characters),
            "multicolor_suggestion_image_count": multicolor_suggestion_images,
            "multicolor_suggestion_image_ratio": _ratio(multicolor_suggestion_images, total_images),
        },
        "review_cross_checks": {
            "quality_reject_but_rating_3_plus": quality_reject_rating_3_plus,
            "identity_reject_but_rating_3_plus": identity_reject_rating_3_plus,
            "quality_identity_usable_but_rating_0": warning_or_pass_rating_0,
        },
    }


def _print_distribution(title: str, values: dict[str, int]) -> None:
    print(title)
    if not values:
        print("  (none)")
        return
    for key, value in sorted(values.items()):
        print(f"  {key}: {value}")


def print_report(report: dict[str, Any]) -> None:
    print("V2 Validation Report")
    for key, value in report["totals"].items():
        print(f"  {key}: {value}")
    _print_distribution("quality_status", report["quality_status_distribution"])
    _print_distribution("identity_status", report["identity_status_distribution"])
    _print_distribution("generation_status", report["generation_status_distribution"])
    print("generation ratios")
    for key, value in report["generation_status_ratios"].items():
        print(f"  {key}: {value}")
    print("auto regeneration")
    auto = report["auto_regeneration"]
    print(f"  characters_with_quality_reject: {auto['characters_with_quality_reject']}")
    print(f"  generated_after_quality_retry: {auto['generated_after_quality_retry']}")
    print(f"  quality_retry_success_rate: {auto['quality_retry_success_rate']}")
    _print_distribution(
        "  quality_reject_count_distribution_per_character",
        auto["quality_reject_count_distribution_per_character"],
    )
    _print_distribution("  identity_prompt_revision_level_distribution", auto["identity_prompt_revision_level_distribution"])
    print("appearance flags")
    for key, value in report["appearance_flags"].items():
        print(f"  {key}: {value}")
    print("review cross-checks")
    for key, value in report["review_cross_checks"].items():
        print(f"  {key}: {value}")


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    init_db()
    db = SessionLocal()
    try:
        report = build_report(db)
        print_report(report)
        write_report(report, args.output)
        print(f"JSON written: {args.output}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
