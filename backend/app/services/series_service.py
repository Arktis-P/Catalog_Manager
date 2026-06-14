import csv
import io
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.character import Character
from app.models.image import Image
from app.models.review import Review
from app.models.series import Series
from app.schemas.series import SeriesCreate, SeriesUpdate


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
            pattern = f"%{search}%"
            query = query.filter(or_(Series.series_tag.ilike(pattern), Series.display_name.ilike(pattern)))

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
        self.db.delete(series)
        self.db.commit()

    def export_csv(self) -> str:
        _, series_list = self.list_series(limit=10000, sort_by="post_count", sort_order="desc")
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
