from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.global_character import GlobalCharacter
from app.routers import review as review_router
from app.services.review_reference_service import (
    ReviewReferenceService,
    extract_wiki_sample_post_ids,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def make_character(db: Session, tag: str = "hakurei_reimu") -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=100,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def make_post(
    post_id: int,
    *,
    preview: str | None = None,
    large: str | None = None,
    file_url: str | None = None,
    file_ext: str = "jpg",
    is_deleted: bool = False,
) -> dict:
    preview_url = preview or f"https://cdn.donmai.us/preview/{post_id}.jpg"
    return {
        "id": post_id,
        "preview_file_url": preview_url,
        "large_file_url": large or f"https://cdn.donmai.us/large/{post_id}.jpg",
        "file_url": file_url or f"https://cdn.donmai.us/file/{post_id}.{file_ext}",
        "file_ext": file_ext,
        "is_deleted": is_deleted,
    }


class FakeDanbooruClient:
    def __init__(
        self,
        *,
        wiki_body: str | None = None,
        posts_by_id: dict[int, dict] | None = None,
        favorite_posts: list[dict] | None = None,
    ):
        self.wiki_body = wiki_body
        self.posts_by_id = posts_by_id or {}
        self.favorite_posts = favorite_posts or []
        self.list_post_tags: list[str] = []

    def get_wiki_page(self, title: str) -> dict | None:
        if self.wiki_body is None:
            return None
        return {"title": title, "body": self.wiki_body}

    def list_posts(self, *, tags: str, limit: int | None = None, page: int = 1) -> list[dict]:
        self.list_post_tags.append(tags)
        if tags.startswith("id:"):
            post = self.posts_by_id.get(int(tags.removeprefix("id:")))
            return [post] if post else []
        return self.favorite_posts[: limit or len(self.favorite_posts)]


def test_extract_wiki_sample_post_ids_preserves_order_dedupes_and_limits() -> None:
    body = "See /posts/77, !post #123, post:55, post #123, post #66, /posts/88, post:99."

    assert extract_wiki_sample_post_ids(body) == [77, 123, 55, 66, 88]


def test_reference_images_prioritize_wiki_then_fill_with_favorites(db: Session) -> None:
    character = make_character(db)
    duplicate_preview = "https://cdn.donmai.us/shared-preview.jpg"
    client = FakeDanbooruClient(
        wiki_body="Samples: !post #10 post:20 /posts/30 post #404.",
        posts_by_id={
            10: make_post(10),
            20: make_post(20, is_deleted=True),
            30: make_post(30, preview=duplicate_preview),
        },
        favorite_posts=[
            make_post(30),
            make_post(40, file_ext="webm"),
            make_post(50, preview=duplicate_preview),
            make_post(60),
            make_post(70, large=None, file_url="https://cdn.donmai.us/file/70.png"),
            make_post(80),
        ],
    )

    result = ReviewReferenceService(db, client=client).get_reference_images(character.id)

    assert result.character_id == character.id
    assert result.tag == "hakurei_reimu"
    assert [(item.post_id, item.source) for item in result.items] == [
        (10, "wiki_sample"),
        (30, "wiki_sample"),
        (60, "favorite"),
        (70, "favorite"),
        (80, "favorite"),
    ]
    assert client.list_post_tags[-1] == "hakurei_reimu order:favcount"


def test_reference_images_normalize_protocol_relative_urls(db: Session) -> None:
    character = make_character(db)
    client = FakeDanbooruClient(
        wiki_body="post #1",
        posts_by_id={
            1: make_post(
                1,
                preview="//cdn.donmai.us/preview/1.jpg",
                large="//cdn.donmai.us/large/1.jpg",
            ),
        },
    )

    result = ReviewReferenceService(db, client=client).get_reference_images(character.id)

    assert result.items[0].thumbnail_url == "https://cdn.donmai.us/preview/1.jpg"
    assert result.items[0].preview_url == "https://cdn.donmai.us/large/1.jpg"


def test_reference_images_exclude_invalid_image_urls(db: Session) -> None:
    character = make_character(db)
    client = FakeDanbooruClient(
        wiki_body="post #1 post #2",
        posts_by_id={
            1: make_post(1, preview="javascript:alert(1)", large="https://cdn.donmai.us/large/1.jpg"),
            2: make_post(2, preview="https://example.test/preview/2.jpg", large="https://cdn.donmai.us/large/2.jpg"),
        },
        favorite_posts=[make_post(3)],
    )

    result = ReviewReferenceService(db, client=client).get_reference_images(character.id)

    assert [(item.post_id, item.source) for item in result.items] == [(3, "favorite")]


def test_reference_images_use_favorites_when_wiki_has_no_samples(db: Session) -> None:
    character = make_character(db, "kirisame_marisa")
    client = FakeDanbooruClient(
        wiki_body="This page has no explicit post references.",
        favorite_posts=[make_post(1), make_post(2)],
    )

    result = ReviewReferenceService(db, client=client).get_reference_images(character.id)

    assert [(item.post_id, item.source) for item in result.items] == [(1, "favorite"), (2, "favorite")]


def test_reference_images_empty_when_no_usable_posts(db: Session) -> None:
    character = make_character(db, "empty_character")
    client = FakeDanbooruClient(
        wiki_body="post #1",
        posts_by_id={1: make_post(1, file_ext="mp4")},
        favorite_posts=[make_post(2, file_ext="zip"), {"id": 3}],
    )

    result = ReviewReferenceService(db, client=client).get_reference_images(character.id)

    assert result.items == []


def test_reference_images_router_success(db: Session) -> None:
    character = make_character(db)
    service = ReviewReferenceService(
        db,
        client=FakeDanbooruClient(
            wiki_body="post #1",
            posts_by_id={1: make_post(1)},
        ),
    )

    response = review_router.get_v2_review_reference_images(character.id, service=service)

    body = response.__dict__
    assert body["character_id"] == character.id
    assert body["tag"] == "hakurei_reimu"
    assert body["items"][0].post_id == 1
    assert body["items"][0].source == "wiki_sample"


def test_reference_images_router_character_not_found(db: Session) -> None:
    with pytest.raises(review_router.HTTPException) as exc_info:
        review_router.get_v2_review_reference_images(999, service=ReviewReferenceService(db))

    assert exc_info.value.status_code == 404
