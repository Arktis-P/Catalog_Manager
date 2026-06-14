"""Seed development data when the database is empty."""

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.character import Character
from app.models.series import Series
from app.schemas.series import SeriesCreate
from app.services.series_service import SeriesService


DEMO_SERIES = [
    SeriesCreate(
        series_tag="zenless_zone_zero",
        display_name="Zenless Zone Zero",
        post_count=45000,
        priority=10,
        status="pending",
        note="Demo series",
    ),
    SeriesCreate(
        series_tag="honkai_star_rail",
        display_name="Honkai: Star Rail",
        post_count=120000,
        priority=9,
        status="collecting",
        note="Demo series",
    ),
    SeriesCreate(
        series_tag="blue_archive",
        display_name="Blue Archive",
        post_count=95000,
        priority=8,
        status="pending",
        note="Demo series",
    ),
]

DEMO_CHARACTERS = [
    {
        "series_tag": "zenless_zone_zero",
        "character_tag": "belle_(zenless_zone_zero)",
        "display_name": "Belle",
        "danbooru_url": "https://danbooru.donmai.us/posts?tags=belle_(zenless_zone_zero)+zenless_zone_zero",
        "post_count": 3200,
        "hair_color": "pink_hair",
        "hair_shape": "short_hair",
        "eye_color": "blue_eyes",
        "feature_tags": "",
        "status": "ready_for_generation",
    },
    {
        "series_tag": "zenless_zone_zero",
        "character_tag": "wise_(zenless_zone_zero)",
        "display_name": "Wise",
        "danbooru_url": "https://danbooru.donmai.us/posts?tags=wise_(zenless_zone_zero)+zenless_zone_zero",
        "post_count": 2800,
        "hair_color": "black_hair",
        "hair_shape": "short_hair",
        "eye_color": "brown_eyes",
        "feature_tags": "",
        "status": "needs_check",
    },
    {
        "series_tag": "honkai_star_rail",
        "character_tag": "kafka_(honkai_star_rail)",
        "display_name": "Kafka",
        "danbooru_url": "https://danbooru.donmai.us/posts?tags=kafka_(honkai_star_rail)+honkai_star_rail",
        "post_count": 8900,
        "multi_color_hair": "streaked_hair",
        "hair_color": "purple_hair",
        "hair_shape": "long_hair",
        "eye_color": "purple_eyes",
        "feature_tags": "sunglasses",
        "status": "confirmed",
        "from_wiki": True,
        "from_posts": True,
    },
]


def seed_demo_data() -> None:
    db: Session = SessionLocal()
    try:
        if db.query(Series).count() > 0:
            return

        series_service = SeriesService(db)
        csv_path = settings.input_dir / "series.csv"
        if csv_path.exists():
            series_service.import_from_file(csv_path)
        else:
            for row in DEMO_SERIES:
                series_service.create_series(row)

        _seed_characters(db)
    finally:
        db.close()


def _seed_characters(db: Session) -> None:
    if db.query(Character).count() > 0:
        return

    series_by_tag = {s.series_tag: s for s in db.query(Series).all()}
    for row in DEMO_CHARACTERS:
        series = series_by_tag.get(row["series_tag"])
        if not series:
            continue
        db.add(
            Character(
                series_id=series.id,
                character_tag=row["character_tag"],
                display_name=row["display_name"],
                danbooru_url=row["danbooru_url"],
                post_count=row["post_count"],
                multi_color_hair=row.get("multi_color_hair"),
                hair_color=row.get("hair_color"),
                hair_shape=row.get("hair_shape"),
                eye_color=row.get("eye_color"),
                feature_tags=row.get("feature_tags"),
                status=row["status"],
                from_wiki=row.get("from_wiki", False),
                from_list_page=row.get("from_list_page", False),
                from_posts=row.get("from_posts", False),
                from_related=row.get("from_related", False),
            )
        )
    db.commit()
