from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import (  # noqa: F401
        appearance_tag_relevance,
        character,
        character_series_link,
        generation_job,
        global_character,
        global_character_generation_job,
        global_character_image,
        global_character_review,
        image,
        review,
        series,
        setting,
    )

    settings.project_root.joinpath("data").mkdir(parents=True, exist_ok=True)
    settings.input_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ("naia_queues", "generated_images", "cover_images", "exports"):
        (settings.output_dir / subdir).mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "generated_images" / "pending_review").mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    _migrate_series_columns()
    _migrate_character_columns()
    _migrate_global_character_columns()
    _migrate_global_character_image_columns()
    _migrate_review_columns()


def _migrate_character_columns() -> None:
    inspector = inspect(engine)
    if "characters" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("characters")}
    migrations = {
        "generation_prompt": "ALTER TABLE characters ADD COLUMN generation_prompt TEXT",
        "gender": "ALTER TABLE characters ADD COLUMN gender VARCHAR(50)",
        "appearance_confirmed": (
            "ALTER TABLE characters ADD COLUMN appearance_confirmed BOOLEAN NOT NULL DEFAULT 0"
        ),
        "source_series_id": "ALTER TABLE characters ADD COLUMN source_series_id INTEGER",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing:
                connection.execute(text(statement))


def _migrate_global_character_columns() -> None:
    inspector = inspect(engine)
    if "global_characters" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("global_characters")}
    migrations = {
        "parent_character_id": "ALTER TABLE global_characters ADD COLUMN parent_character_id INTEGER",
        "primary_hair_color": "ALTER TABLE global_characters ADD COLUMN primary_hair_color VARCHAR(100)",
        "primary_hair_needs_review": (
            "ALTER TABLE global_characters ADD COLUMN primary_hair_needs_review BOOLEAN NOT NULL DEFAULT 0"
        ),
        "base_prompt": "ALTER TABLE global_characters ADD COLUMN base_prompt TEXT",
        "previous_base_prompt": "ALTER TABLE global_characters ADD COLUMN previous_base_prompt TEXT",
        "prompt_revision_reason": "ALTER TABLE global_characters ADD COLUMN prompt_revision_reason TEXT",
        "prompt_revision_level": "ALTER TABLE global_characters ADD COLUMN prompt_revision_level INTEGER",
        "first_post_at": "ALTER TABLE global_characters ADD COLUMN first_post_at DATETIME",
        "generation_status": (
            "ALTER TABLE global_characters ADD COLUMN generation_status VARCHAR(50) NOT NULL DEFAULT 'not_generated'"
        ),
        "generation_attempts": (
            "ALTER TABLE global_characters ADD COLUMN generation_attempts INTEGER NOT NULL DEFAULT 0"
        ),
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing:
                connection.execute(text(statement))


def _migrate_global_character_image_columns() -> None:
    inspector = inspect(engine)
    if "global_character_images" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("global_character_images")}
    migrations = {
        "quality_status": "ALTER TABLE global_character_images ADD COLUMN quality_status VARCHAR(50)",
        "quality_score": "ALTER TABLE global_character_images ADD COLUMN quality_score FLOAT",
        "quality_reasons": "ALTER TABLE global_character_images ADD COLUMN quality_reasons TEXT",
        "quality_checked_at": "ALTER TABLE global_character_images ADD COLUMN quality_checked_at DATETIME",
        "quality_checker_version": (
            "ALTER TABLE global_character_images ADD COLUMN quality_checker_version VARCHAR(50)"
        ),
        "identity_status": "ALTER TABLE global_character_images ADD COLUMN identity_status VARCHAR(50)",
        "character_confidence": "ALTER TABLE global_character_images ADD COLUMN character_confidence FLOAT",
        "hair_color_confidence": "ALTER TABLE global_character_images ADD COLUMN hair_color_confidence FLOAT",
        "conflicting_character_tag": (
            "ALTER TABLE global_character_images ADD COLUMN conflicting_character_tag VARCHAR(255)"
        ),
        "conflicting_character_confidence": (
            "ALTER TABLE global_character_images ADD COLUMN conflicting_character_confidence FLOAT"
        ),
        "identity_reasons": "ALTER TABLE global_character_images ADD COLUMN identity_reasons TEXT",
        "suggested_multicolor_tags": (
            "ALTER TABLE global_character_images ADD COLUMN suggested_multicolor_tags TEXT"
        ),
        "identity_checked_at": "ALTER TABLE global_character_images ADD COLUMN identity_checked_at DATETIME",
        "identity_checker_version": (
            "ALTER TABLE global_character_images ADD COLUMN identity_checker_version VARCHAR(50)"
        ),
        "is_provisional": (
            "ALTER TABLE global_character_images ADD COLUMN is_provisional BOOLEAN NOT NULL DEFAULT 0"
        ),
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing:
                connection.execute(text(statement))


def _migrate_review_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "reviews" in inspector.get_table_names():
            existing = {column["name"] for column in inspector.get_columns("reviews")}
            if "selected_tags" not in existing:
                connection.execute(text("ALTER TABLE reviews ADD COLUMN selected_tags TEXT"))
        if "global_character_reviews" in inspector.get_table_names():
            existing = {column["name"] for column in inspector.get_columns("global_character_reviews")}
            if "selected_tags" not in existing:
                connection.execute(text("ALTER TABLE global_character_reviews ADD COLUMN selected_tags TEXT"))
            if "review_status" not in existing:
                connection.execute(
                    text(
                        "ALTER TABLE global_character_reviews "
                        "ADD COLUMN review_status VARCHAR(50) NOT NULL DEFAULT 'pending'"
                    )
                )
            if "rating_stage" not in existing:
                connection.execute(
                    text(
                        "ALTER TABLE global_character_reviews "
                        "ADD COLUMN rating_stage VARCHAR(50) NOT NULL DEFAULT 'primary'"
                    )
                )


def _migrate_series_columns() -> None:
    inspector = inspect(engine)
    if "series" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("series")}
    migrations = {
        "last_collect_created": "ALTER TABLE series ADD COLUMN last_collect_created INTEGER NOT NULL DEFAULT 0",
        "last_collect_skipped": "ALTER TABLE series ADD COLUMN last_collect_skipped INTEGER NOT NULL DEFAULT 0",
        "last_appearance_updated": (
            "ALTER TABLE series ADD COLUMN last_appearance_updated INTEGER NOT NULL DEFAULT 0"
        ),
        "parent_series_id": "ALTER TABLE series ADD COLUMN parent_series_id INTEGER",
        "merged_moved_count": "ALTER TABLE series ADD COLUMN merged_moved_count INTEGER NOT NULL DEFAULT 0",
        "merged_duplicate_count": (
            "ALTER TABLE series ADD COLUMN merged_duplicate_count INTEGER NOT NULL DEFAULT 0"
        ),
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing:
                connection.execute(text(statement))
        connection.execute(
            text("UPDATE series SET status = 'tagged' WHERE status = 'all_collected'")
        )
