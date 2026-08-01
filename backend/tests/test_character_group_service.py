from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationships
from app.database import Base
from app.models.character_link_suggestion import CharacterLinkSuggestion
from app.models.global_character import GlobalCharacter
from app.models.global_character_image import GlobalCharacterImage
from app.models.global_character_review import GlobalCharacterReview
from app.routers import character_catalog as character_catalog_router
from app.schemas.character_catalog import CharacterGroupActionRequest, CharacterGroupApplyRequest
from app.services.character_group_service import CharacterGroupService, GroupAction
from app.services.character_link_service import CharacterLinkService


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


@pytest.fixture()
def db_no_autoflush() -> Session:
    """production SessionLocal과 동일하게 autoflush=False로 구성된 세션.
    apply_actions 내부의 명시적 flush가 없으면, 배치 안에서 앞선 액션이 스테이징한
    변경을 뒤따르는 액션의 SQL 검증(_child_count 등)이 놓칠 수 있다."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def make_character(db: Session, *, tag: str, post_count: int = 100) -> GlobalCharacter:
    character = GlobalCharacter(
        character_tag=tag,
        display_name=tag.replace("_", " ").title(),
        post_count=post_count,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


def add_image(db: Session, *, character: GlobalCharacter, image_path: str = "some/path.png") -> GlobalCharacterImage:
    image = GlobalCharacterImage(global_character_id=character.id, image_path=image_path)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def add_review(db: Session, *, character: GlobalCharacter, review_status: str) -> GlobalCharacterReview:
    review = GlobalCharacterReview(global_character_id=character.id, review_status=review_status)
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def add_suggestion(
    db: Session,
    *,
    parent: GlobalCharacter,
    child: GlobalCharacter,
    status: str = "pending",
    score: float = 0.8,
) -> CharacterLinkSuggestion:
    suggestion = CharacterLinkSuggestion(
        parent_character_id=parent.id,
        child_character_id=child.id,
        score=score,
        reason="name_similarity",
        status=status,
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


# ── 그룹 정렬 ──────────────────────────────────────────────────────


def test_groups_ordered_conflict_pending_before_settled(db: Session) -> None:
    settled_parent = make_character(db, tag="settled_parent")
    settled_child = make_character(db, tag="settled_child")
    settled_child.parent_character_id = settled_parent.id
    db.commit()

    pending_parent = make_character(db, tag="pending_parent")
    pending_child = make_character(db, tag="pending_child")
    add_suggestion(db, parent=pending_parent, child=pending_child, status="pending")

    # history-only rejected 제안: 실제 자식도, pending 제안도 없으므로 더 이상
    # 그룹 목록에 유령 앵커로 나타나지 않아야 한다.
    rejected_only_parent = make_character(db, tag="rejected_only_parent")
    rejected_only_child = make_character(db, tag="rejected_only_child")
    add_suggestion(db, parent=rejected_only_parent, child=rejected_only_child, status="rejected")

    conflict_parent_a = make_character(db, tag="conflict_parent_a")
    conflict_parent_b = make_character(db, tag="conflict_parent_b")
    conflict_child = make_character(db, tag="conflict_child")
    add_suggestion(db, parent=conflict_parent_a, child=conflict_child, status="pending")
    add_suggestion(db, parent=conflict_parent_b, child=conflict_child, status="pending")

    items, total = CharacterGroupService(db).list_groups(limit=100)
    assert total == 4
    tags = [item.parent.character.character_tag for item in items]
    states = {item.parent.character.character_tag: item.state for item in items}

    assert "rejected_only_parent" not in tags

    assert states["conflict_parent_a"] == "conflict"
    assert states["conflict_parent_b"] == "conflict"
    assert states["pending_parent"] == "pending"
    assert states["settled_parent"] == "settled"

    assert max(tags.index("conflict_parent_a"), tags.index("conflict_parent_b")) < tags.index("pending_parent")
    assert tags.index("pending_parent") < tags.index("settled_parent")


def test_list_groups_excludes_anchors_with_only_rejected_or_superseded_suggestions(db: Session) -> None:
    """suggestion anchor 서브쿼리는 pending 제안만 사용해야 한다: rejected/superseded는
    이력일 뿐이며 앵커를 만들어내면 안 된다. accepted(실제 연결)는 child_counts_sq
    경로로 여전히 발견되어야 한다."""
    rejected_parent = make_character(db, tag="history_rejected_parent")
    rejected_child = make_character(db, tag="history_rejected_child")
    add_suggestion(db, parent=rejected_parent, child=rejected_child, status="rejected")

    superseded_parent = make_character(db, tag="history_superseded_parent")
    superseded_child = make_character(db, tag="history_superseded_child")
    add_suggestion(db, parent=superseded_parent, child=superseded_child, status="superseded")

    accepted_parent = make_character(db, tag="history_accepted_parent")
    accepted_child = make_character(db, tag="history_accepted_child")
    accepted_child.parent_character_id = accepted_parent.id
    db.commit()

    items, total = CharacterGroupService(db).list_groups(state="all", limit=100)
    tags = {item.parent.character.character_tag for item in items}

    assert "history_rejected_parent" not in tags
    assert "history_superseded_parent" not in tags
    assert "history_accepted_parent" in tags
    assert total == 1


# ── 재계산: 거부 이력 보존 ──────────────────────────────────────────


def test_recalculate_group_preserves_rejected_pair(db: Session) -> None:
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=500)
    child = make_character(db, tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)", post_count=10)

    service = CharacterGroupService(db)
    service.recalculate_group(parent)
    db.commit()

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion is not None
    assert suggestion.status == "pending"

    suggestion.status = "rejected"
    suggestion.decided_at = datetime.now(timezone.utc)
    db.commit()

    service.recalculate_group(parent)
    db.commit()
    db.refresh(suggestion)

    assert suggestion.status == "rejected"


def test_recalculate_group_supersedes_pending_pair_that_no_longer_qualifies(db: Session) -> None:
    parent = make_character(db, tag="stale_parent")
    stale_child = make_character(db, tag="totally_unrelated_stale_child")
    add_suggestion(db, parent=parent, child=stale_child, status="pending")

    CharacterGroupService(db).recalculate_group(parent)
    db.commit()

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=stale_child.id)
        .first()
    )
    assert suggestion.status == "superseded"


# ── apply_actions: accept/add/unlink/move ──────────────────────────


def test_apply_accept_links_child_and_marks_suggestion_accepted(db: Session) -> None:
    parent = make_character(db, tag="parent_a")
    child = make_character(db, tag="child_a")
    add_suggestion(db, parent=parent, child=child, status="pending")

    detail = CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="accept", child_id=child.id)])

    db.refresh(child)
    assert child.parent_character_id == parent.id
    assert [member.character.id for member in detail.children] == [child.id]
    assert detail.suggestions == []

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion.status == "accepted"
    assert suggestion.decided_at is not None


def test_apply_add_links_child_without_prior_suggestion(db: Session) -> None:
    parent = make_character(db, tag="parent_b")
    child = make_character(db, tag="child_b")

    detail = CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="add", child_id=child.id)])

    db.refresh(child)
    assert child.parent_character_id == parent.id
    assert detail.state == "settled"


def test_apply_unlink_detaches_child_and_supersedes_suggestion(db: Session) -> None:
    parent = make_character(db, tag="parent_c")
    child = make_character(db, tag="child_c")
    child.parent_character_id = parent.id
    db.commit()

    detail = CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="unlink", child_id=child.id)])

    db.refresh(child)
    assert child.parent_character_id is None
    assert detail.children == []

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion.status == "superseded"


def test_apply_reject_records_status_without_linking(db: Session) -> None:
    parent = make_character(db, tag="parent_reject")
    child = make_character(db, tag="child_reject")
    add_suggestion(db, parent=parent, child=child, status="pending")

    detail = CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="reject", child_id=child.id)])

    db.refresh(child)
    assert child.parent_character_id is None
    assert detail.suggestions == []

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion.status == "rejected"


def test_apply_move_reparents_child_to_new_parent(db: Session) -> None:
    old_parent = make_character(db, tag="old_parent")
    new_parent = make_character(db, tag="new_parent")
    child = make_character(db, tag="movable_child")
    child.parent_character_id = old_parent.id
    db.commit()

    CharacterGroupService(db).apply_actions(
        old_parent.id, [GroupAction(op="move", child_id=child.id, new_parent_id=new_parent.id)]
    )

    db.refresh(child)
    assert child.parent_character_id == new_parent.id

    old_suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=old_parent.id, child_character_id=child.id)
        .first()
    )
    new_suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=new_parent.id, child_character_id=child.id)
        .first()
    )
    assert old_suggestion.status == "superseded"
    assert new_suggestion.status == "accepted"


# ── 트랜잭션 롤백 ──────────────────────────────────────────────────


def test_apply_actions_rolls_back_entire_batch_on_invalid_action(db: Session) -> None:
    parent = make_character(db, tag="parent_d")
    valid_child = make_character(db, tag="valid_child_d")

    service = CharacterGroupService(db)
    with pytest.raises(ValueError):
        service.apply_actions(
            parent.id,
            [
                GroupAction(op="accept", child_id=valid_child.id),
                GroupAction(op="accept", child_id=999_999),
            ],
        )

    db.refresh(valid_child)
    assert valid_child.parent_character_id is None
    assert db.query(CharacterLinkSuggestion).count() == 0


def test_apply_actions_with_autoflush_disabled_catches_staged_move_then_accept_two_level_hierarchy(
    db_no_autoflush: Session,
) -> None:
    """프로덕션 SessionLocal(autoflush=False)을 재현한다. 같은 배치 안에서
    'C를 B 밑으로 move'가 스테이징된 직후 'B를 A 밑으로 accept'가 실행되면,
    B가 A의 자식이 되는 동시에 B 자신도 C라는 자식을 갖게 되어 2단계 깊이
    (A -> B -> C)가 만들어진다. 매 액션 후 명시적 flush가 없으면 accept의
    _child_count(B) 검증이 아직 flush되지 않은 C의 이동을 보지 못해 이 위반을
    놓친다."""
    db = db_no_autoflush
    anchor_a = make_character(db, tag="two_level_anchor_a")
    middle_b = make_character(db, tag="two_level_middle_b")
    child_c = make_character(db, tag="two_level_child_c")
    child_c.parent_character_id = anchor_a.id
    db.commit()

    service = CharacterGroupService(db)
    with pytest.raises(ValueError):
        service.apply_actions(
            anchor_a.id,
            [
                GroupAction(op="move", child_id=child_c.id, new_parent_id=middle_b.id),
                GroupAction(op="accept", child_id=middle_b.id),
            ],
        )

    db.refresh(anchor_a)
    db.refresh(middle_b)
    db.refresh(child_c)
    assert child_c.parent_character_id == anchor_a.id
    assert middle_b.parent_character_id is None
    assert db.query(CharacterLinkSuggestion).count() == 0


# ── 검증: 자기 자신 / 이중 부모 / 순환 / 1단계 깊이 ─────────────────


def test_apply_accept_rejects_self_link(db: Session) -> None:
    parent = make_character(db, tag="self_parent")

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="accept", child_id=parent.id)])


def test_apply_accept_rejects_child_that_already_has_a_parent(db: Session) -> None:
    parent_x = make_character(db, tag="parent_x")
    parent_y = make_character(db, tag="parent_y")
    child = make_character(db, tag="child_xy")
    child.parent_character_id = parent_x.id
    db.commit()

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(parent_y.id, [GroupAction(op="accept", child_id=child.id)])


def test_apply_accept_rejects_when_anchor_itself_has_a_parent(db: Session) -> None:
    grandparent = make_character(db, tag="grandparent")
    parent = make_character(db, tag="parent_with_parent")
    parent.parent_character_id = grandparent.id
    child = make_character(db, tag="would_be_grandchild")
    db.commit()

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="accept", child_id=child.id)])


def test_apply_accept_rejects_when_child_has_its_own_children(db: Session) -> None:
    parent = make_character(db, tag="parent_z")
    child_with_kids = make_character(db, tag="child_with_kids")
    grandchild = make_character(db, tag="grandchild")
    grandchild.parent_character_id = child_with_kids.id
    db.commit()

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(parent.id, [GroupAction(op="accept", child_id=child_with_kids.id)])


def test_apply_move_rejects_new_parent_that_already_has_a_parent(db: Session) -> None:
    old_parent = make_character(db, tag="old_parent_2")
    grandparent = make_character(db, tag="grandparent_2")
    invalid_new_parent = make_character(db, tag="invalid_new_parent")
    invalid_new_parent.parent_character_id = grandparent.id
    child = make_character(db, tag="movable_child_2")
    child.parent_character_id = old_parent.id
    db.commit()

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(
            old_parent.id,
            [GroupAction(op="move", child_id=child.id, new_parent_id=invalid_new_parent.id)],
        )


# ── 기존 단일 연결/해제 회귀 확인 ────────────────────────────────────


def test_existing_direct_link_and_unlink_still_works(db: Session) -> None:
    parent = make_character(db, tag="direct_parent")
    child = make_character(db, tag="direct_child")

    result = CharacterLinkService(db).link_parent(child.id, parent.id)
    assert result.parent_id == parent.id
    db.refresh(child)
    assert child.parent_character_id == parent.id

    CharacterLinkService(db).unlink_parent(child.id)
    db.refresh(child)
    assert child.parent_character_id is None


# ── 그룹 상세: children/suggestions 정렬 (post_count desc, tag asc) ────


def test_group_detail_orders_children_and_suggestions_by_post_count_then_tag(db: Session) -> None:
    parent = make_character(db, tag="sort_parent", post_count=500)

    child_low = make_character(db, tag="sort_child_b_low", post_count=10)
    child_low.parent_character_id = parent.id
    child_high = make_character(db, tag="sort_child_a_high", post_count=50)
    child_high.parent_character_id = parent.id
    child_tie_b = make_character(db, tag="sort_child_tie_b", post_count=30)
    child_tie_b.parent_character_id = parent.id
    child_tie_a = make_character(db, tag="sort_child_tie_a", post_count=30)
    child_tie_a.parent_character_id = parent.id
    db.commit()

    suggestion_low = make_character(db, tag="suggest_low", post_count=5)
    suggestion_high = make_character(db, tag="suggest_high", post_count=90)
    add_suggestion(db, parent=parent, child=suggestion_low, status="pending")
    add_suggestion(db, parent=parent, child=suggestion_high, status="pending")

    detail = CharacterGroupService(db).get_group(parent.id)

    assert [member.character.character_tag for member in detail.children] == [
        "sort_child_a_high",
        "sort_child_tie_a",
        "sort_child_tie_b",
        "sort_child_b_low",
    ]
    assert [item.child.character.character_tag for item in detail.suggestions] == [
        "suggest_high",
        "suggest_low",
    ]


# ── list_groups: include_unlinked (완전 미연결 후보 노출) ──────────────


def test_list_groups_include_unlinked_surfaces_pure_candidates(db: Session) -> None:
    settled_parent = make_character(db, tag="incl_settled_parent")
    settled_child = make_character(db, tag="incl_settled_child")
    settled_child.parent_character_id = settled_parent.id
    db.commit()

    make_character(db, tag="incl_pure_candidate")
    already_a_child = make_character(db, tag="incl_already_child")
    already_a_child.parent_character_id = settled_parent.id
    db.commit()

    service = CharacterGroupService(db)

    default_items, default_total = service.list_groups(limit=100)
    default_tags = {item.parent.character.character_tag for item in default_items}
    assert "incl_pure_candidate" not in default_tags
    assert default_total == 1

    included_items, included_total = service.list_groups(include_unlinked=True, limit=100)
    tags = {item.parent.character.character_tag for item in included_items}
    assert "incl_pure_candidate" in tags
    assert "incl_settled_parent" in tags
    # already-linked children must never surface as anchor candidates themselves
    assert "incl_already_child" not in tags
    assert included_total == 2

    states = {item.parent.character.character_tag: item.state for item in included_items}
    assert states["incl_pure_candidate"] == "unlinked"


def test_list_groups_include_unlinked_total_supports_last_page_calculation(db: Session) -> None:
    for i in range(5):
        make_character(db, tag=f"unlinked_candidate_{i}", post_count=100 - i)

    service = CharacterGroupService(db)
    limit = 2
    _, total = service.list_groups(include_unlinked=True, skip=0, limit=limit)
    assert total == 5

    last_page_skip = ((total - 1) // limit) * limit
    last_page_items, last_page_total = service.list_groups(
        include_unlinked=True, skip=last_page_skip, limit=limit
    )

    assert last_page_total == total
    assert len(last_page_items) == total - last_page_skip


# ── GET 그룹 상세: 읽기 전용 vs 명시적 재계산 ─────────────────────────


def test_get_group_default_does_not_recalculate(db: Session) -> None:
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=500)
    make_character(db, tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)", post_count=10)

    detail = CharacterGroupService(db).get_group(parent.id)

    assert detail is not None
    assert detail.suggestions == []
    assert db.query(CharacterLinkSuggestion).count() == 0


def test_get_group_recalc_true_computes_suggestions(db: Session) -> None:
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=500)
    child = make_character(db, tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)", post_count=10)

    detail = CharacterGroupService(db).get_group(parent.id, recalc=True)

    assert detail is not None
    assert [s.child.character.id for s in detail.suggestions] == [child.id]
    assert db.query(CharacterLinkSuggestion).count() == 1


# ── list_groups: DB 레벨 페이지네이션/정렬 ────────────────────────────


def test_list_groups_paginates_at_db_level_with_accurate_total(db: Session) -> None:
    expected_tags: list[str] = []
    for i in range(5):
        parent = make_character(db, tag=f"page_parent_{i}", post_count=100 - i)
        child = make_character(db, tag=f"page_child_{i}")
        child.parent_character_id = parent.id
        db.commit()
        expected_tags.append(parent.character_tag)

    service = CharacterGroupService(db)
    first_page, total_1 = service.list_groups(skip=0, limit=2)
    second_page, total_2 = service.list_groups(skip=2, limit=2)
    third_page, total_3 = service.list_groups(skip=4, limit=2)

    assert total_1 == total_2 == total_3 == 5
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert len(third_page) == 1

    tags = [item.parent.character.character_tag for item in first_page + second_page + third_page]
    assert tags == expected_tags


# ── list_groups: 서버 사이드 필터 (state/has_image/review_status) ─────


def test_list_groups_filters_by_state(db: Session) -> None:
    settled_parent = make_character(db, tag="filter_settled_parent")
    settled_child = make_character(db, tag="filter_settled_child")
    settled_child.parent_character_id = settled_parent.id
    db.commit()

    pending_parent = make_character(db, tag="filter_pending_parent")
    pending_child = make_character(db, tag="filter_pending_child")
    add_suggestion(db, parent=pending_parent, child=pending_child, status="pending")

    # history-only rejected 제안은 앵커를 만들지 않으므로 어떤 state 필터에도 잡히지 않는다.
    rejected_only_parent = make_character(db, tag="filter_rejected_only_parent")
    rejected_only_child = make_character(db, tag="filter_rejected_only_child")
    add_suggestion(db, parent=rejected_only_parent, child=rejected_only_child, status="rejected")

    conflict_parent_a = make_character(db, tag="filter_conflict_parent_a")
    conflict_parent_b = make_character(db, tag="filter_conflict_parent_b")
    conflict_child = make_character(db, tag="filter_conflict_child")
    add_suggestion(db, parent=conflict_parent_a, child=conflict_child, status="pending")
    add_suggestion(db, parent=conflict_parent_b, child=conflict_child, status="pending")

    service = CharacterGroupService(db)

    conflict_items, conflict_total = service.list_groups(state="conflict", limit=100)
    assert conflict_total == 2
    assert {item.parent.character.character_tag for item in conflict_items} == {
        "filter_conflict_parent_a",
        "filter_conflict_parent_b",
    }

    pending_items, pending_total = service.list_groups(state="pending", limit=100)
    assert pending_total == 1
    assert pending_items[0].parent.character.character_tag == "filter_pending_parent"

    unlinked_items, unlinked_total = service.list_groups(state="unlinked", limit=100)
    assert unlinked_total == 0
    assert unlinked_items == []

    settled_items, settled_total = service.list_groups(state="settled", limit=100)
    assert settled_total == 1
    assert settled_items[0].parent.character.character_tag == "filter_settled_parent"

    all_items, all_total = service.list_groups(state="all", limit=100)
    assert all_total == 4
    assert {item.parent.character.character_tag for item in all_items} == {
        "filter_conflict_parent_a",
        "filter_conflict_parent_b",
        "filter_pending_parent",
        "filter_settled_parent",
    }


def test_list_groups_filters_by_has_image(db: Session) -> None:
    with_image_parent = make_character(db, tag="filter_with_image_parent")
    with_image_child = make_character(db, tag="filter_with_image_child")
    with_image_child.parent_character_id = with_image_parent.id
    db.commit()
    add_image(db, character=with_image_parent)

    without_image_parent = make_character(db, tag="filter_without_image_parent")
    without_image_child = make_character(db, tag="filter_without_image_child")
    without_image_child.parent_character_id = without_image_parent.id
    db.commit()

    service = CharacterGroupService(db)

    has_image_items, has_image_total = service.list_groups(has_image=True, limit=100)
    assert has_image_total == 1
    assert has_image_items[0].parent.character.character_tag == "filter_with_image_parent"

    no_image_items, no_image_total = service.list_groups(has_image=False, limit=100)
    assert no_image_total == 1
    assert no_image_items[0].parent.character.character_tag == "filter_without_image_parent"


def test_list_groups_filters_by_review_status(db: Session) -> None:
    completed_parent = make_character(db, tag="filter_completed_parent")
    completed_child = make_character(db, tag="filter_completed_child")
    completed_child.parent_character_id = completed_parent.id
    db.commit()
    add_review(db, character=completed_parent, review_status="completed")

    explicit_pending_parent = make_character(db, tag="filter_explicit_pending_parent")
    explicit_pending_child = make_character(db, tag="filter_explicit_pending_child")
    explicit_pending_child.parent_character_id = explicit_pending_parent.id
    db.commit()
    add_review(db, character=explicit_pending_parent, review_status="pending")

    no_review_parent = make_character(db, tag="filter_no_review_parent")
    no_review_child = make_character(db, tag="filter_no_review_child")
    no_review_child.parent_character_id = no_review_parent.id
    db.commit()

    service = CharacterGroupService(db)

    completed_items, completed_total = service.list_groups(review_status="completed", limit=100)
    assert completed_total == 1
    assert completed_items[0].parent.character.character_tag == "filter_completed_parent"

    # "pending" 은 명시적 pending 리뷰와 리뷰가 아예 없는 경우를 모두 포함한다
    # (review_service.py의 기존 pending 필터 관례와 동일).
    pending_items, pending_total = service.list_groups(review_status="pending", limit=100)
    assert pending_total == 2
    assert {item.parent.character.character_tag for item in pending_items} == {
        "filter_explicit_pending_parent",
        "filter_no_review_parent",
    }


def test_list_groups_rejects_invalid_state_value(db: Session) -> None:
    with pytest.raises(ValueError):
        CharacterGroupService(db).list_groups(state="not_a_real_state", limit=100)


def test_list_groups_rejects_invalid_review_status_value(db: Session) -> None:
    with pytest.raises(ValueError):
        CharacterGroupService(db).list_groups(review_status="not_a_real_status", limit=100)


# ── move: 라우트 앵커 소속 검증 ────────────────────────────────────────


def test_apply_move_rejects_child_not_belonging_to_route_anchor(db: Session) -> None:
    real_parent = make_character(db, tag="real_owner_parent")
    unrelated_anchor = make_character(db, tag="unrelated_anchor")
    new_parent = make_character(db, tag="move_target_parent")
    child = make_character(db, tag="owned_child")
    child.parent_character_id = real_parent.id
    db.commit()

    with pytest.raises(ValueError):
        CharacterGroupService(db).apply_actions(
            unrelated_anchor.id,
            [GroupAction(op="move", child_id=child.id, new_parent_id=new_parent.id)],
        )

    db.refresh(child)
    assert child.parent_character_id == real_parent.id


# ── apply 액션 개수 상한 ────────────────────────────────────────────


def test_character_group_apply_request_rejects_more_than_100_actions() -> None:
    actions = [CharacterGroupActionRequest(op="accept", child_id=i + 1) for i in range(101)]
    with pytest.raises(ValidationError):
        CharacterGroupApplyRequest(actions=actions)

    # exactly 100 actions must still be accepted
    CharacterGroupApplyRequest(actions=actions[:100])


# ── recalculate_all_batched: keyset 배치 전체 재계산 ─────────────────


def test_recalculate_all_batched_scans_all_top_level_characters_across_multiple_batches(db: Session) -> None:
    parent = make_character(db, tag="kitasan_black_(umamusume)", post_count=500)
    child = make_character(db, tag="kitasan_black_(glided_shrine_to_glory)_(umamusume)", post_count=10)
    unrelated = make_character(db, tag="totally_unrelated_solo_widget", post_count=50)

    service = CharacterGroupService(db)
    summary = service.recalculate_all_batched(batch_size=1)

    assert summary.scanned_anchors == 3

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion is not None
    assert suggestion.status == "pending"
    assert summary.pending_total >= 1

    # recalculation never mutates parent_character_id relationships
    db.refresh(parent)
    db.refresh(child)
    db.refresh(unrelated)
    assert parent.parent_character_id is None
    assert child.parent_character_id is None
    assert unrelated.parent_character_id is None


def test_recalculate_all_batched_skips_already_linked_children_as_anchors(db: Session) -> None:
    parent = make_character(db, tag="skip_test_parent")
    linked_child = make_character(db, tag="skip_test_child")
    linked_child.parent_character_id = parent.id
    db.commit()
    solo = make_character(db, tag="skip_test_solo")

    summary = CharacterGroupService(db).recalculate_all_batched(batch_size=1)

    # only parent + solo are top-level (parent_character_id IS NULL); the
    # already-linked child is never treated as its own anchor.
    assert summary.scanned_anchors == 2


def test_recalculate_all_batched_preserves_rejected_and_accepted_history(db: Session) -> None:
    parent = make_character(db, tag="idem_parent_alpha")
    rejected_child = make_character(db, tag="idem_parent_alpha_(rejected_variant)")
    add_suggestion(db, parent=parent, child=rejected_child, status="rejected")

    accepted_parent = make_character(db, tag="idem_parent_beta")
    accepted_child = make_character(db, tag="idem_child_beta")
    accepted_child.parent_character_id = accepted_parent.id
    add_suggestion(db, parent=accepted_parent, child=accepted_child, status="accepted")
    db.commit()

    CharacterGroupService(db).recalculate_all_batched(batch_size=2)

    rejected_suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=rejected_child.id)
        .first()
    )
    assert rejected_suggestion.status == "rejected"

    accepted_suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=accepted_parent.id, child_character_id=accepted_child.id)
        .first()
    )
    assert accepted_suggestion.status == "accepted"

    db.refresh(accepted_child)
    assert accepted_child.parent_character_id == accepted_parent.id


def test_recalculate_all_batched_is_idempotent(db: Session) -> None:
    make_character(db, tag="idem_check_parent")
    make_character(db, tag="idem_check_parent_(variant)")

    service = CharacterGroupService(db)
    first_summary = service.recalculate_all_batched(batch_size=1)
    suggestion_count_after_first = db.query(CharacterLinkSuggestion).count()

    second_summary = service.recalculate_all_batched(batch_size=1)
    suggestion_count_after_second = db.query(CharacterLinkSuggestion).count()

    assert suggestion_count_after_first == suggestion_count_after_second
    assert first_summary.scanned_anchors == second_summary.scanned_anchors == 2
    assert first_summary.pending_total == second_summary.pending_total


def test_recalculate_all_character_groups_endpoint_returns_compact_counts(db: Session) -> None:
    parent = make_character(db, tag="endpoint_parent_widget")
    child = make_character(db, tag="endpoint_parent_widget_(variant)")

    response = character_catalog_router.recalculate_all_character_groups(
        limit_per_anchor=30,
        group_service=CharacterGroupService(db),
    )

    assert response.scanned_anchors == 2
    assert response.pending_total >= 1

    suggestion = (
        db.query(CharacterLinkSuggestion)
        .filter_by(parent_character_id=parent.id, child_character_id=child.id)
        .first()
    )
    assert suggestion is not None
    assert suggestion.status == "pending"
