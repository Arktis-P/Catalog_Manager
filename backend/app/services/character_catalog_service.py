from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.integrations.danbooru.appearance_extractor import (
    extract_appearance_tags,
    extract_copyright_tags,
    parse_related_tags,
)
from app.integrations.danbooru.character_catalog_collector import CharacterCatalogCollector
from app.integrations.danbooru.client import DanbooruClient
from app.integrations.danbooru.series_collector import tag_to_display_name
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.series import Series
from app.models.setting import Setting
from app.services.db_write_queue import commit_db_session

CatalogProgressCallback = Callable[[dict[str, object]], None]

CHECKPOINT_KEY = "character_catalog_list_last_page"


@dataclass
class CatalogListResult:
    pages_processed: int
    created: int
    updated: int
    last_page: int


@dataclass
class CatalogTagResult:
    character_tag: str
    success: bool
    appearance_ok: bool
    gender_ok: bool
    series_ok: bool
    error: str | None = None


class CharacterCatalogService:
    def __init__(self, db: Session, client: DanbooruClient | None = None):
        self.db = db
        self.client = client or DanbooruClient()
        self.collector = CharacterCatalogCollector(self.client)

    # ---------- 전체 캐릭터 목록 수집 ----------

    def get_checkpoint_page(self) -> int:
        row = self.db.query(Setting).filter(Setting.key == CHECKPOINT_KEY).first()
        if not row or not row.value:
            return 1
        try:
            return max(1, int(row.value))
        except ValueError:
            return 1

    def _save_checkpoint(self, page: int) -> None:
        row = self.db.query(Setting).filter(Setting.key == CHECKPOINT_KEY).first()
        if row:
            row.value = str(page)
        else:
            self.db.add(Setting(key=CHECKPOINT_KEY, value=str(page)))
        commit_db_session(self.db)

    def reset_checkpoint(self) -> None:
        self._save_checkpoint(1)

    def collect_list(
        self,
        *,
        min_post_count: int,
        start_page: int | None = None,
        max_pages: int | None = None,
        progress_callback: CatalogProgressCallback | None = None,
    ) -> CatalogListResult:
        page = start_page if start_page is not None else self.get_checkpoint_page()
        pages_processed = 0
        created = 0
        updated = 0

        while True:
            if max_pages is not None and pages_processed >= max_pages:
                break

            rows, has_more = self.collector.collect_page(page=page, min_post_count=min_post_count)

            for row in rows:
                existing = (
                    self.db.query(GlobalCharacter)
                    .filter(GlobalCharacter.character_tag == row.character_tag)
                    .first()
                )
                if existing:
                    existing.post_count = row.post_count
                    if not existing.display_name:
                        existing.display_name = row.display_name
                    updated += 1
                else:
                    self.db.add(
                        GlobalCharacter(
                            character_tag=row.character_tag,
                            display_name=row.display_name,
                            post_count=row.post_count,
                        )
                    )
                    created += 1

            commit_db_session(self.db)
            pages_processed += 1
            self._save_checkpoint(page + 1)

            if progress_callback:
                progress_callback(
                    {
                        "phase": "listing",
                        "message": f"{page}페이지 처리 완료 · 신규 {created} · 갱신 {updated}",
                        "current": pages_processed,
                        "total": 0,
                        "created": created,
                        "updated": updated,
                    }
                )

            if not has_more:
                break
            page += 1

        return CatalogListResult(pages_processed=pages_processed, created=created, updated=updated, last_page=page)

    # ---------- 통합 태그 수집 (외형 + 성별 + 시리즈) ----------

    def _resolve_or_create_series(self, copyright_tag: str) -> Series:
        series = self.db.query(Series).filter(Series.series_tag == copyright_tag).first()
        if series:
            return series
        series = Series(
            series_tag=copyright_tag,
            display_name=tag_to_display_name(copyright_tag),
            post_count=0,
            priority=0,
            status="pending",
            note="Characters 탭 통합 수집에서 자동 생성됨",
        )
        self.db.add(series)
        self.db.flush()
        return series

    def collect_tags_for_character(self, character: GlobalCharacter) -> CatalogTagResult:
        error_parts: list[str] = []
        appearance_ok = False
        gender_ok = False
        series_ok = False

        try:
            payload = self.client.get_related_tags(character.character_tag, category=None)
            related = parse_related_tags(payload)
        except Exception as exc:
            # related tags 조회 자체가 실패한 경우, 이전 수집에서 이미 completed였던
            # 하위 상태(외형/성별/시리즈)는 이번 실패로 덮어쓰지 않고 그대로 보존한다.
            if character.appearance_status != "completed":
                character.appearance_status = "failed"
            if character.gender_status != "completed":
                character.gender_status = "failed"
            if character.series_status != "completed":
                character.series_status = "failed"
            character.collect_status = (
                "partial"
                if character.appearance_status == "completed" or character.series_status == "completed"
                else "failed"
            )
            character.error_message = str(exc)
            character.retry_count += 1
            character.last_collected_at = datetime.now(timezone.utc)
            commit_db_session(self.db)
            return CatalogTagResult(
                character_tag=character.character_tag,
                success=False,
                appearance_ok=character.appearance_status == "completed",
                gender_ok=character.gender_status == "completed",
                series_ok=character.series_status == "completed",
                error=str(exc),
            )

        try:
            appearance = extract_appearance_tags(related)
            character.multi_color_hair = appearance.multi_color_hair
            character.hair_color = appearance.hair_color
            character.hair_shape = appearance.hair_shape
            character.eye_color = appearance.eye_color
            character.feature_tags = appearance.feature_tags
            has_appearance = any(
                [appearance.hair_color, appearance.hair_shape, appearance.eye_color, appearance.feature_tags]
            )
            character.appearance_status = "completed" if has_appearance else "needs_review"
            appearance_ok = True

            character.gender = appearance.gender
            character.gender_status = "completed" if appearance.gender else "needs_review"
            gender_ok = appearance.gender is not None
        except Exception as exc:
            if character.appearance_status != "completed":
                character.appearance_status = "failed"
            if character.gender_status != "completed":
                character.gender_status = "failed"
            error_parts.append(f"appearance/gender: {exc}")

        try:
            copyright_matches = extract_copyright_tags(related)
            self.db.query(CharacterSeriesLink).filter(
                CharacterSeriesLink.global_character_id == character.id,
                CharacterSeriesLink.is_user_edited.is_(False),
            ).delete()

            for rank, match in enumerate(copyright_matches):
                series = self._resolve_or_create_series(match.name)
                self.db.add(
                    CharacterSeriesLink(
                        global_character_id=character.id,
                        series_id=series.id,
                        copyright_tag=match.name,
                        relevance_rank=rank,
                        is_primary=(rank == 0),
                        is_auto=True,
                        is_user_edited=False,
                    )
                )
            character.series_status = "completed" if copyright_matches else "needs_review"
            series_ok = True
        except Exception as exc:
            if character.series_status != "completed":
                character.series_status = "failed"
            error_parts.append(f"series: {exc}")

        character.error_message = "; ".join(error_parts) or None
        character.last_collected_at = datetime.now(timezone.utc)
        if appearance_ok and series_ok and not error_parts:
            character.collect_status = "completed"
        elif appearance_ok or series_ok:
            character.collect_status = "partial"
        else:
            character.collect_status = "failed"
            character.retry_count += 1

        commit_db_session(self.db)
        return CatalogTagResult(
            character_tag=character.character_tag,
            success=not error_parts,
            appearance_ok=appearance_ok,
            gender_ok=gender_ok,
            series_ok=series_ok,
            error="; ".join(error_parts) or None,
        )

    # ---------- 조회 ----------

    def get_character(self, character_id: int) -> GlobalCharacter | None:
        return (
            self.db.query(GlobalCharacter)
            .options(selectinload(GlobalCharacter.series_links).selectinload(CharacterSeriesLink.series))
            .filter(GlobalCharacter.id == character_id)
            .first()
        )

    def list_characters(
        self,
        *,
        search: str | None = None,
        gender: str | None = None,
        collect_status: str | None = None,
        series_id: int | None = None,
        min_post_count: int | None = None,
        max_post_count: int | None = None,
        sort_by: str = "post_count",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[GlobalCharacter], int]:
        query = self.db.query(GlobalCharacter).options(
            selectinload(GlobalCharacter.series_links).selectinload(CharacterSeriesLink.series)
        )

        if search:
            like = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    GlobalCharacter.character_tag.ilike(like),
                    GlobalCharacter.display_name.ilike(like),
                    GlobalCharacter.hair_color.ilike(like),
                    GlobalCharacter.hair_shape.ilike(like),
                    GlobalCharacter.eye_color.ilike(like),
                )
            )
        if gender:
            query = query.filter(GlobalCharacter.gender == gender)
        if collect_status:
            query = query.filter(GlobalCharacter.collect_status == collect_status)
        if min_post_count is not None:
            query = query.filter(GlobalCharacter.post_count >= min_post_count)
        if max_post_count is not None:
            query = query.filter(GlobalCharacter.post_count <= max_post_count)
        if series_id is not None:
            query = query.join(CharacterSeriesLink).filter(CharacterSeriesLink.series_id == series_id)

        sort_columns = {
            "post_count": GlobalCharacter.post_count,
            "display_name": GlobalCharacter.display_name,
            "character_tag": GlobalCharacter.character_tag,
            "last_collected_at": GlobalCharacter.last_collected_at,
            "collect_status": GlobalCharacter.collect_status,
            "id": GlobalCharacter.id,
        }
        column = sort_columns.get(sort_by, GlobalCharacter.post_count)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc(), GlobalCharacter.id.asc())

        total = query.distinct().count() if series_id is not None else query.count()
        rows = query.distinct().offset(skip).limit(limit).all() if series_id is not None else query.offset(skip).limit(limit).all()
        return rows, total

    def list_failed_ids(self, *, limit: int = 500) -> list[int]:
        rows = (
            self.db.query(GlobalCharacter.id)
            .filter(GlobalCharacter.collect_status.in_(["failed", "partial"]))
            .order_by(GlobalCharacter.post_count.desc())
            .limit(limit)
            .all()
        )
        return [row[0] for row in rows]

    def list_uncollected_ids(self, *, limit: int = 5000) -> list[int]:
        """이미 완전히 수집 완료(collect_status == completed)된 캐릭터는 제외하고,
        나머지(미수집/실패/부분완료/검토필요) 캐릭터의 id를 반환한다."""
        rows = (
            self.db.query(GlobalCharacter.id)
            .filter(GlobalCharacter.collect_status != "completed")
            .order_by(GlobalCharacter.post_count.desc())
            .limit(limit)
            .all()
        )
        return [row[0] for row in rows]
