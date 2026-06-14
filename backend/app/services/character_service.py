from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations.danbooru.character_collector import CharacterCollector, tag_to_display_name
from app.integrations.danbooru.client import DanbooruClient
from app.models.character import Character
from app.models.series import Series


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
    ) -> CharacterCollectResult:
        existing_tags = self.get_existing_tags(series.id)
        discover_limit = None
        if max_characters is not None:
            discover_limit = max_characters + len(existing_tags)

        candidates_map = self.collector.discover_character_tags(
            series.series_tag,
            max_candidates=discover_limit,
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
        elif series.status == "pending":
            series.status = "collecting"

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
    ) -> CharacterCollectResult:
        series = self.db.query(Series).filter(Series.series_tag == series_tag).first()
        if not series:
            raise ValueError(f"Series not found: {series_tag}")
        return self.collect_for_series(series, max_characters=max_characters)

    def collect_batch(
        self,
        *,
        series_ids: list[int] | None = None,
        status: str | None = None,
        limit: int | None = None,
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
            series.status = "collecting"
            self.db.commit()
            result = self.collect_for_series(series)
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
