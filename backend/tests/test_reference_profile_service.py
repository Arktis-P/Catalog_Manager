from __future__ import annotations

from app.services.reference_profile_service import (
    CharacterReferenceProfile,
    build_reference_profile,
)


class FakeDanbooruClient:
    def __init__(self, posts: list[dict[str, object]]) -> None:
        self.posts = posts
        self.calls: list[tuple[str, int, int]] = []

    def list_posts(self, *, tags: str, page: int = 1, limit: int | None = None):
        self.calls.append((tags, page, int(limit or 0)))
        return self.posts[: int(limit or len(self.posts))]


def test_profile_uses_one_solo_metadata_request_and_no_images() -> None:
    posts = [
        {"id": 1, "tag_string_general": "1girl school_uniform black_hair blue_eyes"},
        {"id": 2, "tag_string_general": "1girl school_uniform jacket black_hair"},
        {"id": 3, "tag_string_general": "1girl bikini black_hair"},
    ]
    client = FakeDanbooruClient(posts)

    result = build_reference_profile(client, "test_character", limit=60)

    assert client.calls == [("test_character solo", 1, 60)]
    assert result.sample_count == 3
    assert result.girl_ratio == 1.0
    assert result.boy_ratio == 0.0
    assert result.swimwear_ratio == round(1 / 3, 4)
    assert "school_uniform" in result.common_outfit_tags

    compact = result.to_json()
    assert "file_url" not in compact
    assert "preview" not in compact
    assert "http" not in compact
    assert "image" not in compact


def test_profile_round_trip_remains_compact_metadata() -> None:
    source = CharacterReferenceProfile(
        version="v1.0",
        sample_count=42,
        girl_ratio=0.8,
        boy_ratio=0.1,
        non_human_ratio=0.05,
        swimwear_ratio=0.02,
        underwear_ratio=0.01,
        common_outfit_tags=("uniform", "jacket"),
    )
    restored = CharacterReferenceProfile.from_json(source.to_json())
    assert restored == source


def test_profile_is_unstable_below_minimum_sample() -> None:
    source = CharacterReferenceProfile(
        version="v1.0",
        sample_count=5,
        girl_ratio=1.0,
        boy_ratio=0.0,
        non_human_ratio=0.0,
        swimwear_ratio=0.0,
        underwear_ratio=0.0,
        common_outfit_tags=(),
    )
    assert source.has_stable_sample is False
