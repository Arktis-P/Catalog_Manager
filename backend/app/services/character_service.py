from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, aliased

from app.config import settings
from app.integrations.danbooru.appearance_extractor import normalize_gender
from app.integrations.danbooru.character_collector import CharacterCollector, tag_to_display_name
from app.integrations.danbooru.client import DanbooruClient
from app.integrations.danbooru.wiki_character_collector import WikiCharacterCollector, WikiCharacterCandidate
from app.models.character import Character
from app.models.series import Series
from app.services.db_write_queue import commit_db_session

CollectProgressCallback = Callable[[dict[str, object]], None]

MAX_HUB_SUB_SERIES = 40

CHARACTER_CSV_COLUMNS = [
    "series_tag",
    "series_display_name",
    "source_series_tag",
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
    merged_children: int = 0
    skipped_sub_series: list[str] | None = None
    used_legacy_fallback: bool = False


@dataclass
class CharacterCollectSummary:
    series_processed: int
    total_discovered: int
    total_created: int
    total_skipped_existing: int
    results: list[CharacterCollectResult]


class CharacterService:
    def __init__(
        self,
        db: Session,
        collector: CharacterCollector | None = None,
        wiki_collector: WikiCharacterCollector | None = None,
    ):
        self.db = db
        self.collector = collector or CharacterCollector()
        self.wiki_collector = wiki_collector or WikiCharacterCollector(self.collector.client)

    def get_character(self, character_id: int) -> Character | None:
        return self.db.query(Character).filter(Character.id == character_id).first()

    def get_existing_tags(self, series_id: int) -> set[str]:
        rows = (
            self.db.query(Character.character_tag)
            .filter(Character.series_id == series_id)
            .all()
        )
        return {row[0] for row in rows}

    def _series_character_count(self, series_id: int) -> int:
        return self.db.query(Character.id).filter(Character.series_id == series_id).count()

    @staticmethod
    def _finalize_collect_status(series: Series) -> None:
        """Mark series collected after a successful collect run (including all-skipped re-collects)."""
        if series.status in {"pending", "collecting"}:
            series.status = "collected"

    def _maybe_legacy_fallback(
        self,
        series: Series,
        wiki_result: CharacterCollectResult,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> CharacterCollectResult:
        if not settings.danbooru_character_legacy_fallback:
            return wiki_result
        if self._series_character_count(series.id) > 0:
            return wiki_result

        if progress_callback:
            progress_callback(
                {
                    "phase": "discovering_fallback",
                    "message": (
                        f"위키에서 캐릭터 목록을 찾지 못함 · "
                        f"기존 방식(post/패턴)으로 수집: {series.series_tag}"
                    ),
                    "current": 0,
                    "total": 1,
                    "discovered": wiki_result.discovered,
                }
            )

        legacy_result = self._collect_for_series_legacy(
            series,
            max_characters=max_characters,
            progress_callback=progress_callback,
            manage_status=False,
            post_supplement=True,
        )
        return CharacterCollectResult(
            series_tag=series.series_tag,
            discovered=wiki_result.discovered + legacy_result.discovered,
            created=wiki_result.created + legacy_result.created,
            skipped_existing=wiki_result.skipped_existing + legacy_result.skipped_existing,
            merged_children=wiki_result.merged_children,
            skipped_sub_series=wiki_result.skipped_sub_series,
            used_legacy_fallback=True,
        )

    def collect_for_series(
        self,
        series: Series,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> CharacterCollectResult:
        if settings.danbooru_character_wiki_collect:
            return self._collect_for_series_wiki(
                series,
                max_characters=max_characters,
                progress_callback=progress_callback,
            )
        return self._collect_for_series_legacy(
            series,
            max_characters=max_characters,
            progress_callback=progress_callback,
        )

    def _collect_for_series_wiki(
        self,
        series: Series,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
        _collect_stack: set[int] | None = None,
    ) -> CharacterCollectResult:
        stack = set(_collect_stack or ())
        if series.id in stack:
            return CharacterCollectResult(
                series_tag=series.series_tag,
                discovered=0,
                created=0,
                skipped_existing=0,
            )
        stack.add(series.id)

        target_series = series
        # Hub-series recursive collection is only allowed at the top level to prevent
        # unbounded recursion into unrelated series discovered from sub-series wikis.
        is_top_level = _collect_stack is None
        series.status = "collecting"
        commit_db_session(self.db)

        discovery = self.wiki_collector.discover(series.series_tag, progress_callback=progress_callback)
        skipped_sub_series: list[str] = list(discovery.skipped_sub_series)
        merged_children = 0
        total_discovered = len(discovery.characters)
        total_created = 0
        total_skipped = 0

        if discovery.sub_series_tags and not discovery.characters and is_top_level:
            sub_series_tags = discovery.sub_series_tags[:MAX_HUB_SUB_SERIES]
            if len(discovery.sub_series_tags) > len(sub_series_tags):
                skipped_sub_series.extend(discovery.sub_series_tags[len(sub_series_tags) :])

            for index, sub_tag in enumerate(sub_series_tags, start=1):
                if progress_callback:
                    progress_callback(
                        {
                            "phase": "discovering_wiki_subseries",
                            "message": (
                                f"하위 시리즈 처리 {index}/{len(sub_series_tags)} · "
                                f"{target_series.series_tag} → {sub_tag}"
                            ),
                            "current": index,
                            "total": len(sub_series_tags),
                            "discovered": total_discovered,
                        }
                    )

                child_series = (
                    self.db.query(Series)
                    .filter(Series.series_tag == sub_tag)
                    .first()
                )
                if not child_series:
                    skipped_sub_series.append(sub_tag)
                    continue
                if child_series.parent_series_id is not None:
                    continue
                if child_series.id in stack:
                    skipped_sub_series.append(sub_tag)
                    continue
                if child_series.status == "collecting" and child_series.id != series.id:
                    skipped_sub_series.append(sub_tag)
                    continue

                child_result = self._collect_for_series_wiki(
                    child_series,
                    max_characters=max_characters,
                    progress_callback=progress_callback,
                    _collect_stack=stack,
                )
                total_discovered += child_result.discovered
                total_created += child_result.created
                total_skipped += child_result.skipped_existing
                skipped_sub_series.extend(child_result.skipped_sub_series or [])

                child_char_count = (
                    self.db.query(Character.id).filter(Character.series_id == child_series.id).count()
                )
                if child_char_count <= 0 or child_series.id == target_series.id:
                    continue

                try:
                    from app.services.series_merge_service import SeriesMergeService

                    SeriesMergeService(self.db).merge_into_parent(child_series.id, target_series.id)
                    merged_children += 1
                except ValueError:
                    skipped_sub_series.append(sub_tag)

            target_series.last_collect_created = total_created
            target_series.last_collect_skipped = total_skipped
            self._finalize_collect_status(target_series)
            commit_db_session(self.db)
            result = CharacterCollectResult(
                series_tag=target_series.series_tag,
                discovered=total_discovered,
                created=total_created,
                skipped_existing=total_skipped,
                merged_children=merged_children,
                skipped_sub_series=skipped_sub_series,
            )
            return self._maybe_legacy_fallback(
                target_series,
                result,
                max_characters=max_characters,
                progress_callback=progress_callback,
            )

        created, skipped_existing, discovered = self._save_wiki_candidates(
            target_series,
            discovery.characters,
            max_characters=max_characters,
            progress_callback=progress_callback,
        )
        total_created += created
        total_skipped += skipped_existing
        total_discovered = max(total_discovered, discovered)

        if progress_callback:
            progress_callback(
                {
                    "phase": "saving",
                    "message": "DB에 저장 중...",
                    "current": created,
                    "total": created,
                    "discovered": total_discovered,
                }
            )

        self._finalize_collect_status(target_series)
        target_series.last_collect_created = created
        target_series.last_collect_skipped = skipped_existing
        commit_db_session(self.db)
        result = CharacterCollectResult(
            series_tag=target_series.series_tag,
            discovered=total_discovered,
            created=total_created,
            skipped_existing=total_skipped,
            merged_children=merged_children,
            skipped_sub_series=skipped_sub_series,
        )
        return self._maybe_legacy_fallback(
            target_series,
            result,
            max_characters=max_characters,
            progress_callback=progress_callback,
        )

    def _save_wiki_candidates(
        self,
        series: Series,
        candidates: dict[str, WikiCharacterCandidate],
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
    ) -> tuple[int, int, int]:
        existing_tags = self.get_existing_tags(series.id)
        new_candidates = {
            name: candidate for name, candidate in candidates.items() if name not in existing_tags
        }

        if max_characters is not None:
            new_candidates = dict(list(new_candidates.items())[:max_characters])

        if new_candidates:
            self.wiki_collector.enrich_post_counts(
                series.series_tag,
                new_candidates,
                progress_callback=progress_callback,
            )

        created = 0
        skipped_existing = len(candidates) - len(new_candidates)
        for candidate in new_candidates.values():
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
                    from_wiki=candidate.from_wiki,
                    from_list_page=candidate.from_list_page,
                )
            )
            created += 1
        return created, skipped_existing, len(candidates)

    def _collect_for_series_legacy(
        self,
        series: Series,
        *,
        max_characters: int | None = None,
        progress_callback: CollectProgressCallback | None = None,
        manage_status: bool = True,
        post_supplement: bool | None = None,
    ) -> CharacterCollectResult:
        if manage_status:
            series.status = "collecting"
            commit_db_session(self.db)

        existing_tags = self.get_existing_tags(series.id)
        discover_limit = None
        if max_characters is not None:
            discover_limit = max_characters + len(existing_tags)

        candidates_map = self.collector.discover_character_tags(
            series.series_tag,
            max_candidates=discover_limit,
            post_supplement=post_supplement,
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

        if manage_status:
            self._finalize_collect_status(series)

        series.last_collect_created = created
        series.last_collect_skipped = skipped_existing

        commit_db_session(self.db)
        return CharacterCollectResult(
            series_tag=series.series_tag,
            discovered=len(candidates_map),
            created=created,
            skipped_existing=skipped_existing,
            used_legacy_fallback=True,
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
        commit_db_session(self.db)
        self.db.refresh(character)
        return character

    def delete_character(self, character_id: int) -> str:
        character = self.get_character(character_id)
        if not character:
            raise ValueError("Character not found")
        tag = character.character_tag
        self.db.delete(character)
        commit_db_session(self.db)
        return tag

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
        status: str | None = None,
    ):
        SourceSeries = aliased(Series)
        query = (
            self.db.query(Character, Series, SourceSeries)
            .join(Series, Character.series_id == Series.id)
            .outerjoin(SourceSeries, Character.source_series_id == SourceSeries.id)
        )
        if series_id is not None:
            query = query.filter(Character.series_id == series_id)
        if status:
            query = query.filter(Character.status == status.strip())
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
        status: str | None = None,
        skip: int = 0,
        limit: int = 500,
    ) -> tuple[list[tuple[Character, Series, Series | None]], int]:
        query = self._character_rows_query(series_id=series_id, search=search, status=status)
        total = query.count()
        rows = query.offset(skip).limit(limit).all()
        return rows, total

    @staticmethod
    def _character_csv_row(
        character: Character,
        series: Series,
        source_series: Series | None = None,
    ) -> list[object]:
        return [
            series.series_tag,
            series.display_name,
            source_series.series_tag if source_series is not None else "",
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
        for character, series, source_series in rows:
            writer.writerow(self._character_csv_row(character, series, source_series))
        return output.getvalue()
