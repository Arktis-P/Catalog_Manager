from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.integrations.danbooru.client import DanbooruClient
from app.models.global_character import GlobalCharacter
from app.models.global_character_review import GlobalCharacterReview

REFERENCE_PROFILE_VERSION = "v1.0"
REFERENCE_POST_LIMIT = 60
MIN_REFERENCE_SAMPLE = 12

SWIMWEAR_TAGS = frozenset(
    {
        "bikini",
        "swimsuit",
        "school_swimsuit",
        "one-piece_swimsuit",
        "competition_swimsuit",
        "micro_bikini",
        "string_bikini",
        "swim_briefs",
        "swim_trunks",
    }
)
UNDERWEAR_TAGS = frozenset(
    {
        "underwear",
        "underwear_only",
        "bra",
        "panties",
        "lingerie",
        "sports_bra",
        "boxers",
        "briefs",
    }
)
NON_HUMAN_TAGS = frozenset(
    {
        "no_humans",
        "animal_focus",
        "creature",
        "monster",
        "mascot",
        "feral",
        "pokemon_(creature)",
    }
)
OUTFIT_TAGS = frozenset(
    {
        *SWIMWEAR_TAGS,
        *UNDERWEAR_TAGS,
        "school_uniform",
        "military_uniform",
        "maid",
        "dress",
        "kimono",
        "jacket",
        "hoodie",
        "suit",
        "armor",
        "bodysuit",
        "gym_uniform",
        "sailor_collar",
        "serafuku",
    }
)


@dataclass(frozen=True)
class CharacterReferenceProfile:
    """Compact metadata-only baseline used for pending image inspection.

    The profile intentionally stores no Danbooru image bytes, image URLs, thumbnails,
    or embeddings. It is derived from post tag metadata only and is small enough to
    cache per character without turning the catalogue into a second image archive.
    """

    version: str
    sample_count: int
    girl_ratio: float
    boy_ratio: float
    non_human_ratio: float
    swimwear_ratio: float
    underwear_ratio: float
    common_outfit_tags: tuple[str, ...]

    def to_json(self) -> str:
        payload = asdict(self)
        payload["common_outfit_tags"] = list(self.common_outfit_tags)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | None) -> CharacterReferenceProfile | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return cls(
                version=str(payload.get("version") or ""),
                sample_count=int(payload.get("sample_count") or 0),
                girl_ratio=float(payload.get("girl_ratio") or 0.0),
                boy_ratio=float(payload.get("boy_ratio") or 0.0),
                non_human_ratio=float(payload.get("non_human_ratio") or 0.0),
                swimwear_ratio=float(payload.get("swimwear_ratio") or 0.0),
                underwear_ratio=float(payload.get("underwear_ratio") or 0.0),
                common_outfit_tags=tuple(str(tag) for tag in payload.get("common_outfit_tags") or ()),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    @property
    def has_stable_sample(self) -> bool:
        return self.sample_count >= MIN_REFERENCE_SAMPLE


@dataclass(frozen=True)
class PendingReferenceContext:
    """Cheap local context available without any Danbooru request."""

    non_human_candidate_score: float
    cached_profile: CharacterReferenceProfile | None


def _post_tags(post: dict[str, object]) -> set[str]:
    # Danbooru keeps 1girl/1boy/outfit/no_humans in general tags. Meta tags are
    # intentionally ignored because they add little identity value and increase noise.
    raw = str(post.get("tag_string_general") or "")
    return {part.strip().lower() for part in raw.split() if part.strip()}


def _ratio(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def build_reference_profile(
    client: DanbooruClient,
    character_tag: str,
    *,
    limit: int = REFERENCE_POST_LIMIT,
) -> CharacterReferenceProfile:
    """Build a baseline from `{character_tag} solo` metadata without downloading images."""
    posts = client.list_posts(tags=f"{character_tag} solo", page=1, limit=max(1, min(limit, 100)))
    sample_count = len(posts)
    girl = 0
    boy = 0
    non_human = 0
    swimwear = 0
    underwear = 0
    outfit_counts: Counter[str] = Counter()

    for post in posts:
        tags = _post_tags(post)
        girl += int("1girl" in tags or "multiple_girls" in tags)
        boy += int("1boy" in tags or "multiple_boys" in tags)
        non_human += int(bool(tags & NON_HUMAN_TAGS))
        swimwear += int(bool(tags & SWIMWEAR_TAGS))
        underwear += int(bool(tags & UNDERWEAR_TAGS))
        for tag in tags & OUTFIT_TAGS:
            outfit_counts[tag] += 1

    common_outfits = tuple(tag for tag, _count in outfit_counts.most_common(6))
    return CharacterReferenceProfile(
        version=REFERENCE_PROFILE_VERSION,
        sample_count=sample_count,
        girl_ratio=_ratio(girl, sample_count),
        boy_ratio=_ratio(boy, sample_count),
        non_human_ratio=_ratio(non_human, sample_count),
        swimwear_ratio=_ratio(swimwear, sample_count),
        underwear_ratio=_ratio(underwear, sample_count),
        common_outfit_tags=common_outfits,
    )


def is_pending_character(db: Session, character_id: int) -> bool:
    review = (
        db.query(GlobalCharacterReview)
        .filter(GlobalCharacterReview.global_character_id == character_id)
        .first()
    )
    return review is None or review.review_status == "pending"


def cached_reference_profile(character: GlobalCharacter) -> CharacterReferenceProfile | None:
    profile = CharacterReferenceProfile.from_json(character.reference_profile)
    if profile is None or profile.version != REFERENCE_PROFILE_VERSION:
        return None
    return profile


def get_or_build_reference_profile(
    db: Session,
    character: GlobalCharacter,
    *,
    force: bool = False,
    allow_network: bool = False,
    client_factory: Callable[[], DanbooruClient] = DanbooruClient,
) -> CharacterReferenceProfile | None:
    """Return a compact cached profile for a pending character.

    The default is cache-only. Callers must explicitly set `allow_network=True` (or
    `force=True`) before a cache miss may perform the one metadata request. This keeps
    a large pending backfill from accidentally issuing one Danbooru call per character.
    """
    if not is_pending_character(db, character.id):
        return None
    if not force:
        cached = cached_reference_profile(character)
        if cached is not None:
            return cached
    if not allow_network and not force:
        return None

    try:
        profile = build_reference_profile(client_factory(), character.character_tag)
    except Exception:
        # Reference data is an optional confidence booster. Inspection must remain
        # usable when Danbooru credentials/network are unavailable.
        return None

    character.reference_profile = profile.to_json()
    character.reference_profile_version = REFERENCE_PROFILE_VERSION
    character.reference_profile_updated_at = datetime.now()
    db.flush()
    return profile


def get_pending_reference_context(character_tag: str) -> PendingReferenceContext | None:
    """Read only local cached context for one pending character.

    This is intentionally separated from profile building so the common inspection
    path does not make one Danbooru request per character.
    """
    from app.database import SessionLocal

    with SessionLocal() as db:
        character = (
            db.query(GlobalCharacter)
            .filter(GlobalCharacter.character_tag == character_tag)
            .first()
        )
        if character is None or not is_pending_character(db, character.id):
            return None
        return PendingReferenceContext(
            non_human_candidate_score=float(character.non_human_candidate_score or 0.0),
            cached_profile=cached_reference_profile(character),
        )


def get_reference_profile_for_tag(
    character_tag: str,
    *,
    build_if_missing: bool = True,
) -> CharacterReferenceProfile | None:
    """Bridge for image checkers; network is explicit on cache misses."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        character = (
            db.query(GlobalCharacter)
            .filter(GlobalCharacter.character_tag == character_tag)
            .first()
        )
        if character is None or not is_pending_character(db, character.id):
            return None
        cached = cached_reference_profile(character)
        if cached is not None or not build_if_missing:
            return cached
        profile = get_or_build_reference_profile(
            db,
            character,
            allow_network=True,
        )
        if profile is not None:
            db.commit()
        return profile
