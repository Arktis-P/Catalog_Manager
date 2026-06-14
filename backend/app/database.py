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
        character,
        generation_job,
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

    Base.metadata.create_all(bind=engine)
    _migrate_series_columns()


def _migrate_series_columns() -> None:
    inspector = inspect(engine)
    if "series" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("series")}
    migrations = {
        "last_collect_created": "ALTER TABLE series ADD COLUMN last_collect_created INTEGER NOT NULL DEFAULT 0",
        "last_collect_skipped": "ALTER TABLE series ADD COLUMN last_collect_skipped INTEGER NOT NULL DEFAULT 0",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing:
                connection.execute(text(statement))
