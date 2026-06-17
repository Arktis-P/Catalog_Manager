import csv
import io
from pathlib import Path

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.character import Character
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.schemas.series import SeriesCreate, SeriesUpdate, SeriesResponse


def _escape_like_pattern(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


class SeriesService:
    def __init__(self, db: Session):
        self.db = db

    def list_series(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "post_count",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Series], int]:
        query = self.db.query(Series)

        if status:
            query = query.filter(Series.status == status)
        if search:
            pattern = f"%{_escape_like_pattern(search.strip())}%"
            query = query.filter(
                or_(
                    Series.series_tag.ilike(pattern, escape="\\"),
                    Series.display_name.ilike(pattern, escape="\\"),
                )
            )

        sort_columns = {
            "post_count": Series.post_count,
            "priority": Series.priority,
            "series_tag": Series.series_tag,
            "display_name": Series.display_name,
            "status": Series.status,
            "updated_at": Series.updated_at,
        }
        sort_column = sort_columns.get(sort_by, Series.post_count)
        if sort_order == "asc":
            query = query.order_by(sort_column.asc(), Series.id.asc())
        else:
            query = query.order_by(sort_column.desc(), Series.id.asc())

        total = query.count()
        items = query.offset(skip).limit(limit).all()
        return items, total

    def get_character_counts(self, series_ids: list[int]) -> dict[int, int]:
        if not series_ids:
            return {}
        rows = (
            self.db.query(Character.series_id, func.count(Character.id))
            .filter(Character.series_id.in_(series_ids))
            .group_by(Character.series_id)
            .all()
        )
        return {series_id: count for series_id, count in rows}

    def get_appearance_extracted_counts(self, series_ids: list[int]) -> dict[int, int]:
        if not series_ids:
            return {}
        rows = (
            self.db.query(Character.series_id, func.count(Character.id))
            .filter(Character.series_id.in_(series_ids), Character.from_related.is_(True))
            .group_by(Character.series_id)
            .all()
        )
        return {series_id: count for series_id, count in rows}

    def get_own_character_counts(self, series_ids: list[int]) -> dict[int, int]:
        if not series_ids:
            return {}
        rows = (
            self.db.query(Character.series_id, func.count(Character.id))
            .filter(Character.series_id.in_(series_ids), Character.source_series_id.is_(None))
            .group_by(Character.series_id)
            .all()
        )
        return {series_id: count for series_id, count in rows}

    def get_child_counts(self, series_ids: list[int]) -> dict[int, int]:
        if not series_ids:
            return {}
        rows = (
            self.db.query(Series.parent_series_id, func.count(Series.id))
            .filter(Series.parent_series_id.in_(series_ids))
            .group_by(Series.parent_series_id)
            .all()
        )
        return {parent_id: count for parent_id, count in rows if parent_id is not None}

    def get_generation_pipeline_done_flags(self, series_ids: list[int]) -> dict[int, bool]:
        if not series_ids:
            return {}

        has_cover = exists(
            select(1).where(
                Image.character_id == Character.id,
                Image.is_cover.is_(True),
            )
        )
        eligible_filters = (
            Character.series_id.in_(series_ids),
            Character.appearance_confirmed.is_(True),
            Character.generation_prompt.isnot(None),
            Character.generation_prompt != "",
            Character.status != "excluded",
        )
        eligible_rows = (
            self.db.query(Character.series_id, func.count(Character.id))
            .filter(*eligible_filters)
            .group_by(Character.series_id)
            .all()
        )
        completed_rows = (
            self.db.query(Character.series_id, func.count(Character.id))
            .join(Review, Review.character_id == Character.id)
            .filter(
                *eligible_filters,
                Review.review_status == "completed",
                has_cover,
            )
            .group_by(Character.series_id)
            .all()
        )
        eligible_map = {series_id: count for series_id, count in eligible_rows}
        completed_map = {series_id: count for series_id, count in completed_rows}

        completed_status_ids = {
            row[0]
            for row in self.db.query(Series.id)
            .filter(Series.id.in_(series_ids), Series.status == "completed")
            .all()
        }

        return {
            series_id: (
                series_id in completed_status_ids
                or (
                    eligible_map.get(series_id, 0) > 0
                    and completed_map.get(series_id, 0) >= eligible_map.get(series_id, 0)
                )
            )
            for series_id in series_ids
        }

    def to_response(
        self,
        series: Series,
        *,
        character_count: int | None = None,
        own_character_count: int | None = None,
        appearance_extracted_count: int | None = None,
        parent_series_tag: str | None = None,
        child_count: int = 0,
        generation_pipeline_done: bool = False,
    ) -> SeriesResponse:
        is_merged_child = series.parent_series_id is not None
        resolved_character_count = character_count if character_count is not None else 0
        resolved_own_count = own_character_count if own_character_count is not None else resolved_character_count
        resolved_appearance_count = (
            appearance_extracted_count if appearance_extracted_count is not None else 0
        )
        if is_merged_child and series.merged_moved_count > 0:
            display_character_count = series.merged_moved_count
        else:
            display_character_count = resolved_character_count

        return SeriesResponse(
            id=series.id,
            series_tag=series.series_tag,
            display_name=series.display_name,
            post_count=series.post_count,
            priority=series.priority,
            status=series.status,
            note=series.note,
            parent_series_id=series.parent_series_id,
            parent_series_tag=parent_series_tag,
            character_count=display_character_count,
            own_character_count=resolved_own_count,
            merged_moved_count=series.merged_moved_count,
            merged_duplicate_count=series.merged_duplicate_count,
            child_count=child_count,
            is_merged_child=is_merged_child,
            last_collect_created=series.last_collect_created,
            last_collect_skipped=series.last_collect_skipped,
            last_appearance_updated=series.last_appearance_updated,
            appearance_extracted_count=resolved_appearance_count,
            all_appearance_collected=(
                resolved_character_count > 0
                and resolved_appearance_count >= resolved_character_count
            ),
            generation_pipeline_done=generation_pipeline_done,
            created_at=series.created_at,
            updated_at=series.updated_at,
        )

    def to_response_list(self, items: list[Series]) -> list[SeriesResponse]:
        if not items:
            return []
        series_ids = [series.id for series in items]
        counts = self.get_character_counts(series_ids)
        own_counts = self.get_own_character_counts(series_ids)
        appearance_counts = self.get_appearance_extracted_counts(series_ids)
        child_counts = self.get_child_counts(series_ids)
        pipeline_done_flags = self.get_generation_pipeline_done_flags(series_ids)

        parent_ids = {series.parent_series_id for series in items if series.parent_series_id}
        parent_tags: dict[int, str] = {}
        if parent_ids:
            parent_rows = self.db.query(Series.id, Series.series_tag).filter(Series.id.in_(parent_ids)).all()
            parent_tags = {row[0]: row[1] for row in parent_rows}

        return [
            self.to_response(
                series,
                character_count=counts.get(series.id, 0),
                own_character_count=own_counts.get(series.id, 0),
                appearance_extracted_count=appearance_counts.get(series.id, 0),
                parent_series_tag=parent_tags.get(series.parent_series_id) if series.parent_series_id else None,
                child_count=child_counts.get(series.id, 0),
                generation_pipeline_done=pipeline_done_flags.get(series.id, False),
            )
            for series in items
        ]

    def flatten_hierarchical(self, items: list[SeriesResponse]) -> list[SeriesResponse]:
        by_id = {item.id: item for item in items}
        children_by_parent: dict[int, list[SeriesResponse]] = {}
        roots: list[SeriesResponse] = []
        orphans: list[SeriesResponse] = []

        for item in items:
            if item.parent_series_id and item.parent_series_id in by_id:
                children_by_parent.setdefault(item.parent_series_id, []).append(item)
            elif item.parent_series_id:
                orphans.append(item)
            elif not item.is_merged_child:
                roots.append(item)

        roots.sort(key=lambda row: row.post_count, reverse=True)
        for child_list in children_by_parent.values():
            child_list.sort(key=lambda row: row.series_tag)

        ordered: list[SeriesResponse] = []
        for root in roots:
            ordered.append(root)
            ordered.extend(children_by_parent.get(root.id, []))
        ordered.extend(orphans)
        ordered.extend(item for item in items if item.is_merged_child and item not in ordered)
        return ordered

    def get_series(self, series_id: int) -> Series | None:
        return self.db.query(Series).filter(Series.id == series_id).first()

    def get_by_tag(self, series_tag: str) -> Series | None:
        return self.db.query(Series).filter(Series.series_tag == series_tag).first()

    def create_series(self, data: SeriesCreate) -> Series:
        series = Series(**data.model_dump())
        self.db.add(series)
        self.db.commit()
        self.db.refresh(series)
        return series

    def update_series(self, series: Series, data: SeriesUpdate) -> Series:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(series, field, value)
        self.db.commit()
        self.db.refresh(series)
        return series

    def delete_series(self, series: Series) -> None:
        child_count = self.db.query(Series.id).filter(Series.parent_series_id == series.id).count()
        if child_count > 0:
            raise ValueError("Unmerge sub-series before deleting this series.")
        self.db.delete(series)
        self.db.commit()

    def export_csv(self) -> str:
        series_list, _ = self.list_series(limit=10000, sort_by="post_count", sort_order="desc")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["series_tag", "display_name", "post_count", "priority", "status", "note"])
        for series in series_list:
            writer.writerow(
                [
                    series.series_tag,
                    series.display_name,
                    series.post_count,
                    series.priority,
                    series.status,
                    series.note or "",
                ]
            )
        return output.getvalue()

    def import_csv(self, content: str, *, replace: bool = False, batch_size: int = 1000) -> dict[str, int]:
        reader = csv.DictReader(io.StringIO(content))
        required = {"series_tag", "display_name", "post_count", "priority", "status", "note"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV must contain columns: series_tag, display_name, post_count, priority, status, note")

        if replace:
            self.db.query(Series).delete()
            self.db.commit()

        created = 0
        updated = 0
        merged_duplicates = 0
        pending: dict[str, Series] = {}

        for row_index, row in enumerate(reader, start=1):
            series_tag = (row.get("series_tag") or "").strip()
            if not series_tag:
                continue

            payload = {
                "display_name": (row.get("display_name") or "").strip(),
                "post_count": int(row.get("post_count") or 0),
                "priority": int(row.get("priority") or 0),
                "status": (row.get("status") or "pending").strip(),
                "note": (row.get("note") or "").strip() or None,
            }

            existing = pending.get(series_tag)
            if existing is None:
                existing = self.get_by_tag(series_tag)

            if existing:
                for field, value in payload.items():
                    setattr(existing, field, value)
                if series_tag in pending:
                    merged_duplicates += 1
                else:
                    updated += 1
            else:
                series = Series(series_tag=series_tag, **payload)
                self.db.add(series)
                pending[series_tag] = series
                created += 1

            if batch_size > 0 and row_index % batch_size == 0:
                self.db.commit()
                pending.clear()

        self.db.commit()
        return {
            "created": created,
            "updated": updated,
            "merged_duplicates": merged_duplicates,
        }

    def import_from_file(self, file_path: Path, *, replace: bool = False) -> dict[str, int]:
        content = file_path.read_text(encoding="utf-8-sig")
        return self.import_csv(content, replace=replace)
