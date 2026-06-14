from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.integrations.danbooru.client import DanbooruClient

DEFAULT_EXCLUDES = {"original"}


@dataclass
class SeriesRow:
    series_tag: str
    display_name: str
    post_count: int
    priority: int
    status: str
    note: str

    def to_csv_row(self) -> list[str | int]:
        return [
            self.series_tag,
            self.display_name,
            self.post_count,
            self.priority,
            self.status,
            self.note,
        ]


def tag_to_display_name(series_tag: str) -> str:
    name = series_tag.replace("_", " ")
    name = re.sub(r"\(([^)]+)\)", r" (\1)", name)
    return name.strip().title()


def load_exclude_tags(path: Path | None = None) -> set[str]:
    exclude_path = path or settings.input_dir / "series_exclude.txt"
    if not exclude_path.exists():
        return set(DEFAULT_EXCLUDES)

    tags = set(DEFAULT_EXCLUDES)
    for line in exclude_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            tags.add(value)
    return tags


class SeriesTagCollector:
    def __init__(self, client: DanbooruClient | None = None):
        self.client = client or DanbooruClient()
        self.exclude_tags = load_exclude_tags()

    def collect(
        self,
        *,
        max_tags: int | None = None,
        max_pages: int | None = None,
        min_post_count: int = 1,
        start_page: int = 1,
    ) -> list[SeriesRow]:
        rows: list[SeriesRow] = []
        page = start_page
        priority = 1

        while True:
            if max_pages is not None and page > start_page + max_pages - 1:
                break

            tags = self.client.list_copyright_tags(page=page, limit=1000)
            if not tags:
                break

            for tag in tags:
                name = tag.get("name", "").strip()
                post_count = int(tag.get("post_count") or 0)
                if not name or name in self.exclude_tags:
                    continue
                if post_count < min_post_count:
                    continue

                rows.append(
                    SeriesRow(
                        series_tag=name,
                        display_name=tag_to_display_name(name),
                        post_count=post_count,
                        priority=priority,
                        status="pending",
                        note="",
                    )
                )
                priority += 1

                if max_tags is not None and len(rows) >= max_tags:
                    return rows

            if len(tags) < 1000:
                break
            page += 1

        return rows

    def write_csv(self, rows: list[SeriesRow], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["series_tag", "display_name", "post_count", "priority", "status", "note"])
            for row in rows:
                writer.writerow(row.to_csv_row())

    def write_checkpoint(self, path: Path, *, page: int, collected: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "page": page,
            "collected": collected,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
