from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.danbooru.client import DanbooruClient
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.global_character import GlobalCharacter
from app.services.db_write_queue import commit_db_session
from app.services.settings_service import SettingsService


HAIR_REVIEW_MARGIN = 0.05
SMALL_SAMPLE_UPPER_BOUND = 100
FLOAT_COMPARISON_EPSILON = 1e-12


@dataclass(frozen=True)
class RelevanceConfig:
    min_cooccurrence: int
    threshold_hair_shape: float
    threshold_multicolor: float
    threshold_eye_color: float
    threshold_feature: float
    small_sample_bonus: float
    min_posts_auto_confirm: int
    feature_tag_whitelist: tuple[str, ...]

    @classmethod
    def from_settings(cls, service: SettingsService) -> "RelevanceConfig":
        values = service.get_public_settings()
        whitelist = tuple(
            dict.fromkeys(
                tag.strip()
                for tag in str(values["v2_feature_tag_whitelist"]).split(",")
                if tag.strip()
            )
        )
        return cls(
            min_cooccurrence=int(values["v2_relevance_min_cooccurrence"]),
            threshold_hair_shape=float(values["v2_relevance_threshold_hair_shape"]),
            threshold_multicolor=float(values["v2_relevance_threshold_multicolor"]),
            threshold_eye_color=float(values["v2_relevance_threshold_eye_color"]),
            threshold_feature=float(values["v2_relevance_threshold_feature"]),
            small_sample_bonus=float(values["v2_relevance_small_sample_bonus"]),
            min_posts_auto_confirm=int(values["v2_relevance_min_posts_auto_confirm"]),
            feature_tag_whitelist=whitelist,
        )


@dataclass(frozen=True)
class CollectedRelevance:
    tag: str
    tag_category: str
    cooccurrence_count: int
    character_post_count: int
    relevance_score: float
    is_prompt_candidate: bool
    is_confirmed: bool


@dataclass(frozen=True)
class CharacterRelevanceResult:
    character_id: int
    character_tag: str
    character_post_count: int
    collected_count: int
    primary_hair_color: str | None
    primary_hair_needs_review: bool
    first_post_at: datetime | None


class TagRelevanceService:
    def __init__(
        self,
        db: Session,
        client: DanbooruClient | None = None,
        config: RelevanceConfig | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.config = config or RelevanceConfig.from_settings(SettingsService(db))

    @staticmethod
    def _split_tags(value: str | None) -> list[str]:
        if not value:
            return []
        return [tag.strip() for tag in value.split(",") if tag.strip()]

    def candidate_tags(self, character: GlobalCharacter) -> dict[str, str]:
        candidates: dict[str, str] = {}
        fields = (
            ("hair_color", character.hair_color),
            ("hair_shape", character.hair_shape),
            ("multicolor", character.multi_color_hair),
            ("eye_color", character.eye_color),
            ("feature", character.feature_tags),
        )
        for category, raw_tags in fields:
            for tag in self._split_tags(raw_tags):
                candidates.setdefault(tag, category)
        for tag in self.config.feature_tag_whitelist:
            candidates.setdefault(tag, "feature")
        return candidates

    def _threshold_for(self, category: str, post_count: int) -> float | None:
        base = {
            "hair_shape": self.config.threshold_hair_shape,
            "multicolor": self.config.threshold_multicolor,
            "eye_color": self.config.threshold_eye_color,
            "feature": self.config.threshold_feature,
        }.get(category)
        if base is None:
            return None
        if self.config.min_posts_auto_confirm <= post_count < SMALL_SAMPLE_UPPER_BOUND:
            return base + self.config.small_sample_bonus
        return base

    @staticmethod
    def _parse_post_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _fetch_first_post_at(self, character_tag: str) -> datetime | None:
        if self.client is None:
            raise RuntimeError("Danbooru client is required for collection")
        posts = self.client.list_posts(tags=f"{character_tag} order:id_asc", limit=1)
        if not posts:
            return None
        return self._parse_post_datetime(posts[0].get("created_at"))

    def collect_for_character(self, character: GlobalCharacter) -> CharacterRelevanceResult:
        if self.client is None:
            self.client = DanbooruClient()
        candidates = self.candidate_tags(character)
        post_count = self.client.count_posts(character.character_tag)
        raw_rows: list[tuple[str, str, int, float]] = []
        for tag, category in candidates.items():
            cooccurrence = self.client.count_posts(f"{character.character_tag} {tag}")
            score = cooccurrence / post_count if post_count > 0 else 0.0
            raw_rows.append((tag, category, cooccurrence, score))

        first_post_at = self._fetch_first_post_at(character.character_tag)
        hair_rows = sorted(
            (row for row in raw_rows if row[1] == "hair_color"),
            key=lambda row: (-row[3], -row[2], row[0]),
        )
        primary_hair_color = hair_rows[0][0] if hair_rows else None
        hair_needs_review = bool(
            len(hair_rows) > 1 and hair_rows[0][3] - hair_rows[1][3] < HAIR_REVIEW_MARGIN
        )

        selected: list[CollectedRelevance] = []
        for tag, category, cooccurrence, score in raw_rows:
            if category == "hair_color":
                passes = tag == primary_hair_color and cooccurrence >= self.config.min_cooccurrence
            else:
                threshold = self._threshold_for(category, post_count)
                passes = (
                    threshold is not None
                    and cooccurrence >= self.config.min_cooccurrence
                    and score + FLOAT_COMPARISON_EPSILON >= threshold
                )
            selected.append(
                CollectedRelevance(
                    tag=tag,
                    tag_category=category,
                    cooccurrence_count=cooccurrence,
                    character_post_count=post_count,
                    relevance_score=score,
                    is_prompt_candidate=passes,
                    is_confirmed=passes and post_count >= self.config.min_posts_auto_confirm,
                )
            )

        now = datetime.now(timezone.utc)
        current_tags = {row.tag for row in selected}
        existing_rows = {
            row.tag: row
            for row in self.db.query(CharacterAppearanceTagRelevance)
            .filter(CharacterAppearanceTagRelevance.global_character_id == character.id)
            .all()
        }
        for stale_tag, stale_row in existing_rows.items():
            if stale_tag not in current_tags:
                stale_row.is_prompt_candidate = False
                stale_row.is_confirmed = False

        for item in selected:
            row = existing_rows.get(item.tag)
            if row is None:
                row = CharacterAppearanceTagRelevance(
                    global_character_id=character.id,
                    tag=item.tag,
                    tag_category=item.tag_category,
                )
                self.db.add(row)
            row.tag_category = item.tag_category
            row.cooccurrence_count = item.cooccurrence_count
            row.character_post_count = item.character_post_count
            row.relevance_score = item.relevance_score
            row.is_prompt_candidate = item.is_prompt_candidate
            row.is_confirmed = item.is_confirmed
            row.collected_at = now

        character.primary_hair_color = primary_hair_color
        character.primary_hair_needs_review = hair_needs_review
        character.first_post_at = first_post_at
        commit_db_session(self.db)

        return CharacterRelevanceResult(
            character_id=character.id,
            character_tag=character.character_tag,
            character_post_count=post_count,
            collected_count=len(selected),
            primary_hair_color=primary_hair_color,
            primary_hair_needs_review=hair_needs_review,
            first_post_at=first_post_at,
        )

    def list_for_character(self, character_id: int) -> list[CharacterAppearanceTagRelevance]:
        return (
            self.db.query(CharacterAppearanceTagRelevance)
            .filter(CharacterAppearanceTagRelevance.global_character_id == character_id)
            .order_by(
                CharacterAppearanceTagRelevance.tag_category.asc(),
                CharacterAppearanceTagRelevance.relevance_score.desc(),
                CharacterAppearanceTagRelevance.tag.asc(),
            )
            .all()
        )
