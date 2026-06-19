from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.series import Series
from app.services.db_write_queue import commit_db_session

STATUSES_LOCKED_FOR_GENERATION = frozenset({"disabled", "completed"})


def queue_covers_all_eligible_characters(
    character_ids: list[int] | None,
    queue_payload: dict[str, object],
) -> bool:
    characters = queue_payload.get("characters")
    if not isinstance(characters, list) or not characters:
        return False

    eligible_ids = {
        item["id"]
        for item in characters
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    if not eligible_ids:
        return False

    if not character_ids:
        return True

    return set(character_ids) == eligible_ids


def mark_series_generating(db: Session, series: Series) -> str:
    previous = series.status
    if series.status not in STATUSES_LOCKED_FOR_GENERATION:
        series.status = "generating"
        commit_db_session(db)
    return previous


def restore_series_status(db: Session, series: Series, previous_status: str) -> None:
    if series.status != "generating":
        return
    if previous_status and previous_status not in STATUSES_LOCKED_FOR_GENERATION:
        series.status = previous_status
    elif series.status == "generating":
        series.status = "tagged"
    commit_db_session(db)


def finalize_series_after_batch(
    db: Session,
    series: Series,
    *,
    previous_status: str,
    batch_success: bool,
    marks_series_generated: bool,
) -> None:
    if batch_success and marks_series_generated:
        if series.status not in STATUSES_LOCKED_FOR_GENERATION:
            series.status = "generated"
            commit_db_session(db)
        return

    restore_series_status(db, series, previous_status)
