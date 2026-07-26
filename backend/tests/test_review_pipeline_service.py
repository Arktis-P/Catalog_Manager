from __future__ import annotations

import json

import pytest
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.appearance_tag_relevance import CharacterAppearanceTagRelevance
from app.models.character_series_link import CharacterSeriesLink
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.models.parent_child_candidate_dismissal import ParentChildCandidateDismissal
from app.models.series import Series
from app.routers import review as review_router
from app.schemas.review import NonHumanDecisionRequest, ParentChildApplyRequest
from app.services.review_pipeline_service import ReviewPipelineService


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


def make_series(db: Session, tag: str) -> Series:
    series = Series(series_tag=tag, display_name=tag.replace("_", " ").title(), post_count=1000)
    db.add(series)
    db.commit()
    db.refresh(series)
    return series


def make_character(
    db: Session,
    *,
    tag: str,
    post_count: int = 100,
    series: Series | None = None,
    review_status: str | None = None,
    rating: int | None = None,
    gender: str | None = None,
    with_image: bool = True,
) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=post_count,
        gender=gender,
        generation_status="generated" if with_image else "not_generated",
        hair_color="black_hair",
        eye_color="blue_eyes",
    )
    if with_image:
        character.images.append(
            GlobalCharacterImage(
                image_path=f"/tmp/{tag}.png",
                auto_status="pass",
                cover_score=0.9,
                identity_status="match",
            )
        )
    if review_status:
        character.review = GlobalCharacterReview(
            review_status=review_status,
            rating=rating,
            gender=gender,
        )
    if series:
        character.series_links.append(
            CharacterSeriesLink(
                series_id=series.id,
                copyright_tag=series.series_tag,
                relevance_rank=0,
                is_primary=True,
            )
        )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def test_parent_child_group_puts_existing_parent_first_and_includes_image_missing_child(db: Session) -> None:
    series = make_series(db, "hololive")
    parent = make_character(db, tag="murasaki_shion", post_count=500, series=series, review_status="completed", rating=4)
    existing = make_character(db, tag="murasaki_shion_(1st_costume)", post_count=40, series=series, review_status="pending")
    missing_image = make_character(db, tag="murasaki_shion_(2nd_costume)", post_count=30, series=series, with_image=False)
    make_character(db, tag="gawr_gura", post_count=999, series=series)
    existing.parent_character_id = parent.id
    db.commit()

    group = ReviewPipelineService(db).get_parent_child_group(parent.id)

    assert group.parent.character.id == parent.id
    child_tags = [item.character.character_tag for item in group.children]
    assert child_tags[:2] == ["murasaki_shion_(1st_costume)", "murasaki_shion_(2nd_costume)"]
    assert "gawr_gura" not in child_tags
    assert group.children[0].already_linked is True
    assert group.children[1].default_selected is True


def test_parent_child_apply_is_atomic_and_does_not_overwrite_conflicting_tags(db: Session) -> None:
    parent = make_character(db, tag="hero", rating=3, review_status="completed", gender="1girl")
    child = make_character(db, tag="hero_(summer)", gender=None)
    invalid_child = make_character(db, tag="hero_(winter)")
    grandchild = make_character(db, tag="hero_(winter)_(alt)")
    grandchild.parent_character_id = invalid_child.id
    db.commit()

    service = ReviewPipelineService(db)
    with pytest.raises(ValueError):
        service.apply_parent_child_group(
            parent.id,
            ParentChildApplyRequest(
                selected_child_ids=[child.id, invalid_child.id],
                apply_parent_rating=True,
                complete_children=True,
            ),
        )
    db.refresh(child)
    assert child.parent_character_id is None

    child.eye_color = "green_eyes"
    db.commit()
    result = service.apply_parent_child_group(
        parent.id,
        ParentChildApplyRequest(
            selected_child_ids=[child.id],
            apply_parent_rating=True,
            complete_children=True,
        ),
    )
    db.refresh(child)
    assert child.parent_character_id == parent.id
    assert child.gender == "1girl"
    assert child.eye_color == "green_eyes"
    assert result.conflicts[0]["field"] == "eye_color"
    assert child.review.rating == 3
    assert child.review.review_status == "completed"


def test_parent_child_dismiss_persists_unlinked_candidate_and_unlinks_existing_child(db: Session) -> None:
    parent = make_character(db, tag="hero", post_count=100)
    candidate = make_character(db, tag="hero_(summer)", post_count=80)
    linked = make_character(db, tag="hero_(winter)", post_count=70)
    linked.parent_character_id = parent.id
    db.commit()

    service = ReviewPipelineService(db)
    unlinked = service.dismiss_parent_child_candidate(parent.id, candidate.id, reason="not same outfit family")
    assert unlinked is False
    assert db.query(ParentChildCandidateDismissal).count() == 1
    assert candidate.id not in [item.character.id for item in service.get_parent_child_group(parent.id).children]

    unlinked = service.dismiss_parent_child_candidate(parent.id, linked.id)
    db.refresh(linked)
    assert unlinked is True
    assert linked.parent_character_id is None


def test_parent_child_apply_rejects_unrelated_selection_and_invalid_unlink(db: Session) -> None:
    parent = make_character(db, tag="hero")
    candidate = make_character(db, tag="hero_(summer)")
    unrelated = make_character(db, tag="totally_unrelated")
    other_parent = make_character(db, tag="villain")
    linked_elsewhere = make_character(db, tag="villain_(summer)")
    linked_elsewhere.parent_character_id = other_parent.id
    db.commit()

    service = ReviewPipelineService(db)
    with pytest.raises(ValueError, match="not a candidate"):
        service.apply_parent_child_group(parent.id, ParentChildApplyRequest(selected_child_ids=[unrelated.id]))
    with pytest.raises(ValueError, match="not currently linked"):
        service.apply_parent_child_group(parent.id, ParentChildApplyRequest(unlink_child_ids=[linked_elsewhere.id]))

    result = service.apply_parent_child_group(parent.id, ParentChildApplyRequest(selected_child_ids=[candidate.id]))
    assert result.linked_child_ids == [candidate.id]


def test_parent_child_group_list_total_and_pages_use_actual_groups(db: Session) -> None:
    make_character(db, tag="lonely_root", post_count=999)
    parent_a = make_character(db, tag="alpha", post_count=500)
    make_character(db, tag="alpha_(summer)", post_count=50)
    parent_b = make_character(db, tag="beta", post_count=400)
    dismissed = make_character(db, tag="beta_(summer)", post_count=40)
    service = ReviewPipelineService(db)
    service.dismiss_parent_child_candidate(parent_b.id, dismissed.id, reason="wrong beta")

    page = service.list_parent_child_groups(skip=0, limit=10)
    assert page[1] == 1
    assert [group.parent.character.id for group in page[0]] == [parent_a.id]

    empty_page = service.list_parent_child_groups(skip=1, limit=10)
    assert empty_page[0] == []
    assert empty_page[1] == 1


def test_parent_child_group_list_uses_sql_eligibility_and_limits_group_fetches(db: Session) -> None:
    for index in range(250):
        make_character(db, tag=f"lonely_root_{index:03d}", post_count=10_000 - index)
    parents = [make_character(db, tag=f"batch_parent_{index:03d}", post_count=1000 - index) for index in range(6)]
    for parent in parents:
        make_character(db, tag=f"{parent.character_tag}_(summer)", post_count=10)
    db.commit()

    service = ReviewPipelineService(db)
    calls = 0
    original_get_group = service.get_parent_child_group

    def counted_get_group(parent_id: int, *, confidence: str = "all"):
        nonlocal calls
        calls += 1
        return original_get_group(parent_id, confidence=confidence)

    service.get_parent_child_group = counted_get_group  # type: ignore[method-assign]
    groups, total = service.list_parent_child_groups(skip=0, limit=2)

    assert total == 6
    assert len(groups) == 2
    assert calls == 2


def test_parent_child_group_list_query_count_does_not_scale_with_lonely_roots(db: Session) -> None:
    for index in range(300):
        make_character(db, tag=f"unused_root_{index:03d}", post_count=20_000 - index)
    parent = make_character(db, tag="query_parent", post_count=100)
    make_character(db, tag="query_parent_(alt)", post_count=10)
    db.commit()

    statement_count = 0

    def before_cursor_execute(*_args):
        nonlocal statement_count
        statement_count += 1

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", before_cursor_execute)
    try:
        groups, total = ReviewPipelineService(db).list_parent_child_groups(skip=0, limit=1)
    finally:
        event.remove(bind, "before_cursor_execute", before_cursor_execute)

    assert total == 1
    assert [group.parent.character.id for group in groups] == [parent.id]
    assert statement_count <= 18


def test_danbooru_reference_images_are_lazy_metadata_only(monkeypatch, db: Session) -> None:
    character = make_character(db, tag="hakurei_reimu")

    class FakeClient:
        def list_posts(self, *, tags: str, limit: int):
            assert tags == "hakurei_reimu order:rank"
            return [
                {"id": 1, "is_deleted": False, "preview_file_url": "p1", "large_file_url": "s1", "file_url": "f1", "rating": "s"},
                {"id": 2, "is_deleted": True, "preview_file_url": "p2"},
                {"id": 3, "is_deleted": False},
                {"id": 4, "is_deleted": False, "preview_file_url": "p4"},
                {"id": 5, "is_deleted": False, "large_file_url": "s5"},
                {"id": 6, "is_deleted": False, "preview_file_url": "p6"},
            ]

    monkeypatch.setattr("app.services.review_pipeline_service.DanbooruClient", FakeClient)

    payload = ReviewPipelineService(db).get_danbooru_reference_images(character.id, limit=3)

    assert [image["post_id"] for image in payload["images"]] == [1, 4, 5]
    assert payload["images"][0]["post_url"].endswith("/posts/1")
    assert "binary" not in json.dumps(payload["images"])


def test_non_human_candidates_score_decision_and_general_review_preserve_user_result(db: Session) -> None:
    pokemon = make_series(db, "pokemon")
    creature = make_character(db, tag="pikachu", series=pokemon, gender="other", with_image=False)
    trainer = make_character(db, tag="misty_(pokemon)", series=pokemon, gender="1girl")
    creature.appearance_relevances.append(
        CharacterAppearanceTagRelevance(
            tag="pokemon_(creature)",
            tag_category="general",
            cooccurrence_count=100,
            character_post_count=100,
            relevance_score=0.9,
        )
    )
    trainer.images[0].auto_tags = json.dumps(["1girl", "human"])
    db.commit()

    response = review_router.list_non_human_candidates(
        review_filter="unreviewed",
        category=None,
        series_id=None,
        search=None,
        include_completed=False,
        skip=0,
        limit=30,
        service=ReviewPipelineService(db),
    )
    by_tag = {item.character_tag: item for item in response.items}
    assert by_tag["pikachu"].score > by_tag["misty_(pokemon)"].score

    decision = review_router.apply_non_human_decision(
        creature.id,
        NonHumanDecisionRequest(result="non_human"),
        service=ReviewPipelineService(db),
    )
    assert decision.rating == -1
    assert decision.review_status == "completed"
    db.refresh(creature)
    assert creature.review.non_human_review_result == "non_human"

    general = review_router.apply_non_human_decision(
        trainer.id,
        NonHumanDecisionRequest(result="general_review"),
        service=ReviewPipelineService(db),
    )
    assert general.rating is None
    assert general.review_status == "pending"
    db.refresh(trainer)
    assert trainer.review.non_human_review_result == "general_review"


def test_non_human_category_filter_is_applied_before_pagination(db: Session) -> None:
    pokemon = make_series(db, "pokemon")
    make_character(db, tag="tagger_first", post_count=999).images[0].auto_tags = json.dumps(["no_humans"])
    creature = make_character(db, tag="pikachu", post_count=1, series=pokemon, gender="other")
    db.commit()

    items, total = ReviewPipelineService(db).list_non_human_candidates(category="series", skip=0, limit=1)

    assert total == 1
    assert [item.character.id for item in items] == [creature.id]


def test_non_human_decision_requires_explicit_overwrite_or_reopen(db: Session) -> None:
    completed = make_character(db, tag="pikachu", review_status="completed", rating=5, gender="other")
    service = ReviewPipelineService(db)

    with pytest.raises(ValueError, match="Completed review"):
        service.apply_non_human_decision(completed.id, result="non_human")
    with pytest.raises(ValueError, match="Existing rating"):
        service.apply_non_human_decision(
            completed.id,
            result="non_human",
            reopen_completed=True,
        )

    service.apply_non_human_decision(
        completed.id,
        result="non_human",
        reopen_completed=True,
        overwrite_existing=True,
    )
    db.refresh(completed)
    assert completed.review.rating == -1
