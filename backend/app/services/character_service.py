from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.danbooru.character_collector import CharacterCollector, tag_to_display_name
from app.integrations.danbooru.client import DanbooruClient
from app.models.character import Character
from app.models.series import Series

CollectProgressCallback = Callable[[dict[str, object]], None]

CHARACTER_CSV_COLUMNS = [
    "series_tag",
    "series_display_name",
    "character_tag",
    "display_name",
    "post_count",
    "danbooru_url",
    "multi_color_hair",
    "hair_color",
    "hair_shape",
    "eye_color",
    "feature_tags",
    "gender",
    "generation_prompt",
    "appearance_confirmed",
    "status",
    "from_wiki",
    "from_list_page",
    "from_posts",
    "from_related",
    "needs_check_reason",
]


@dataclass
class CharacterCollectResult:
    series_tag: str
    discovered: int
    created: int
    skipped_existing: int


@dataclass
class CharacterCollectSummary:
    series_processed: int
    total_discovered: int
    total_created: int
    total_skipped_existing: int
    results: list[CharacterCollectResult]


class CharacterService:
    def __init__(self, db: Session, collector: CharacterCollector | None = None):
        self.db = db
        self.collector = collector or CharacterCollector()

    def get_character(self, character_id: int) -> Character | None:
        return self.db.query(Character).filter(Character.id == character_id).first()

    def get_existing_tags(self, series_id: int) -> set[str]:
        rows = (
            self.db.query(Character.character_tag)
            .filter(Character.series_id == series_id)
            .all()
        )
        return {row[0] for row in rows}

    def collect_for_series(
        self,
        series: Series,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> CharacterCollectResult:
        series.status = "collecting"
        self.db.commit()

        existing_tags = self.get_existing_tags(series.id)
        discover_limit = None
        if max_characters is not None:
            discover_limit = max_characters + len(existing_tags)

        candidates_map = self.collector.discover_character_tags(
            series.series_tag,
            max_candidates=discover_limit,
            progress_callback=progress_callback,
        )
        new_candidates_map = {
            name: candidate for name, candidate in candidates_map.items() if name not in existing_tags
        }

        if max_characters is not None:
            new_candidates_map = dict(list(new_candidates_map.items())[:max_characters])

        self.collector.enrich_post_counts(
            series.series_tag,
            new_candidates_map,
            progress_label=series.series_tag,
            progress_callback=progress_callback,
        )

        if progress_callback:
            progress_callback(
                {
                    "phase": "saving",
                    "message": "DB에 저장 중...",
                    "current": 0,
                    "total": len(new_candidates_map),
                    "discovered": len(candidates_map),
                }
            )

        created = 0
        skipped_existing = len(candidates_map) - len(new_candidates_map)
        for candidate in new_candidates_map.values():
            if candidate.post_count <= 0:
                continue

            self.db.add(
                Character(
                    series_id=series.id,
                    character_tag=candidate.character_tag,
                    display_name=tag_to_display_name(candidate.character_tag),
                    danbooru_url=DanbooruClient.build_danbooru_url(
                        candidate.character_tag,
                        series.series_tag,
                    ),
                    post_count=candidate.post_count,
                    status="needs_check",
                    from_posts=candidate.from_posts,
                )
            )
            created += 1

        if created:
            series.status = "collected" if series.status in {"pending", "collecting"} else series.status
        elif series.status == "collecting":
            series.status = "collecting"

        series.last_collect_created = created
        series.last_collect_skipped = skipped_existing

        self.db.commit()
        return CharacterCollectResult(
            series_tag=series.series_tag,
            discovered=len(candidates_map),
            created=created,
            skipped_existing=skipped_existing,
        )

    def collect_for_series_tag(
        self,
        series_tag: str,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> CharacterCollectResult:
        series = self.db.query(Series).filter(Series.series_tag == series_tag).first()
        if not series:
            raise ValueError(f"Series not found: {series_tag}")
        return self.collect_for_series(
            series,
            max_characters=max_characters,
            progress_callback=progress_callback,
        )

    def update_character_series(self, character_id: int, series_id: int) -> Character:
        character = self.get_character(character_id)
        if not character:
            raise ValueError("Character not found")

        series = self.db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise ValueError("Series not found")

        if character.series_id == series_id:
            return character

        duplicate = (
            self.db.query(Character)
            .filter(
                Character.series_id == series_id,
                Character.character_tag == character.character_tag,
                Character.id != character_id,
            )
            .first()
        )
        if duplicate:
            raise ValueError(
                f"Character tag already exists for series '{series.series_tag}': {character.character_tag}"
            )

        character.series_id = series_id
        character.danbooru_url = DanbooruClient.build_danbooru_url(
            character.character_tag,
            series.series_tag,
        )
        character.post_count = self.collector.client.count_posts(
            DanbooruClient.build_search_tags(character.character_tag, series.series_tag)
        )
        character.status = "needs_check"
        character.needs_check_reason = f"Moved to series '{series.series_tag}'"
        self.db.commit()
        self.db.refresh(character)
        return character

    def collect_batch(
        self,
        *,
        series_ids: list[int] | None = None,
        status: str | None = None,
        limit: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> CharacterCollectSummary:
        query = self.db.query(Series).order_by(Series.post_count.desc(), Series.id.asc())
        if series_ids:
            query = query.filter(Series.id.in_(series_ids))
        if status:
            query = query.filter(Series.status == status)
        if limit is not None:
            query = query.limit(limit)

        series_list = query.all()
        results: list[CharacterCollectResult] = []
        total_discovered = 0
        total_created = 0
        total_skipped = 0

        for series in series_list:
            result = self.collect_for_series(series, progress_callback=progress_callback)
            results.append(result)
            total_discovered += result.discovered
            total_created += result.created
            total_skipped += result.skipped_existing

        return CharacterCollectSummary(
            series_processed=len(series_list),
            total_discovered=total_discovered,
            total_created=total_created,
            total_skipped_existing=total_skipped,
            results=results,
        )

    def _character_rows_query(
        self,
        *,
        series_id: int | None = None,
        search: str | None = None,
    ):
        query = self.db.query(Character, Series).join(Series, Character.series_id == Series.id)
        if series_id is not None:
            query = query.filter(Character.series_id == series_id)
        if search:
            like = f"%{search.strip()}%"
            query = query.filter(
                Character.character_tag.ilike(like)
                | Character.display_name.ilike(like)
                | Series.series_tag.ilike(like)
                | Series.display_name.ilike(like)
            )
        return query.order_by(
            Series.series_tag.asc(),
            Character.post_count.desc(),
            Character.character_tag.asc(),
        )

    def list_characters(
        self,
        *,
        series_id: int | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 500,
    ) -> tuple[list[tuple[Character, Series]], int]:
        query = self._character_rows_query(series_id=series_id, search=search)
        total = query.count()
        rows = query.offset(skip).limit(limit).all()
        return rows, total

    @staticmethod
    def _character_csv_row(character: Character, series: Series) -> list[object]:
        return [
            series.series_tag,
            series.display_name,
            character.character_tag,
            character.display_name,
            character.post_count,
            character.danbooru_url or "",
            character.multi_color_hair or "",
            character.hair_color or "",
            character.hair_shape or "",
            character.eye_color or "",
            character.feature_tags or "",
            normalize_gender(character.gender) or "",
            character.generation_prompt or "",
            character.appearance_confirmed,
            character.status,
            character.from_wiki,
            character.from_list_page,
            character.from_posts,
            character.from_related,
            character.needs_check_reason or "",
        ]

    def export_csv(
        self,
        *,
        series_id: int | None = None,
        search: str | None = None,
    ) -> str:
        rows = self._character_rows_query(series_id=series_id, search=search).all()
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow(CHARACTER_CSV_COLUMNS)
        for character, series in rows:
            writer.writerow(self._character_csv_row(character, series))
        return output.getvalue()
